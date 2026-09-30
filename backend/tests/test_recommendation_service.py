"""Focused tests for the production recommendation service."""

import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.osu.client import OsuTopPlay, OsuUserProfile
from backend.app.osu.client import OsuNetworkError
from backend.app.recommendation.service import (
    CANDIDATE_TOP_PLAYS,
    DISCOVERY_PLAYER_LIMIT,
    HYDRATION_BUDGET,
    RANKING_PLAYER_LIMIT,
    SEED_COUNT,
    RecommendationContext,
    RecommendationRequestAccounting,
    RecommendationResult,
    RefreshedTarget,
    build_hybrid_ranking,
    generate_recommendations,
)
from backend.tests.test_selection_expansion_analysis import _recovery


class RecommendationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        recovery = _recovery()
        self.ranking = recovery.ranking_result
        self.profile = recovery.target_preference_profile
        assert self.ranking is not None
        assert self.profile is not None

    def test_hybrid_uses_native_evidence_and_expansion_only_maps(self) -> None:
        ordered = build_hybrid_ranking(self.ranking, self.profile)
        by_id = {
            item.preference_evidence.collaborative.candidate_map.beatmap_id: item
            for item in ordered
        }
        self.assertIn(101, by_id)
        self.assertIn(104, by_id)
        self.assertEqual(by_id[101].preference_evidence.collaborative.support_count, 2)

    def test_target_top_plays_are_excluded_and_order_is_deterministic(self) -> None:
        first = build_hybrid_ranking(self.ranking, self.profile)
        second = build_hybrid_ranking(self.ranking, self.profile)
        target_ids = set(self.ranking.target_beatmap_ids)
        first_ids = [_id(item) for item in first]
        self.assertFalse(target_ids.intersection(first_ids))
        self.assertEqual(first_ids, [_id(item) for item in second])

    def test_rejected_fields_do_not_appear_in_production_ordering(self) -> None:
        assert self.profile.star_rating is not None
        first_players = tuple(
            replace(
                player,
                hydrated_top_plays=tuple(
                    replace(play, star_rating=self.profile.star_rating.first_quartile)
                    for play in player.hydrated_top_plays
                ),
            )
            for player in self.ranking.candidates
        )
        changed_players = tuple(
            replace(
                player,
                acquisition_group=(
                    "one_hit" if player.acquisition_group == "recurring" else "recurring"
                ),
                hydrated_top_plays=tuple(
                    replace(play, star_rating=self.profile.star_rating.third_quartile)
                    for play in reversed(player.hydrated_top_plays)
                ),
            )
            for player in self.ranking.candidates
        )
        first = build_hybrid_ranking(
            replace(self.ranking, candidates=first_players), self.profile
        )
        changed = build_hybrid_ranking(
            replace(self.ranking, candidates=changed_players), self.profile
        )
        self.assertEqual([_id(item) for item in first], [_id(item) for item in changed])


class RecommendationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        recovery = _recovery()
        self.ranking = recovery.ranking_result
        assert self.ranking is not None
        self.target = RefreshedTarget(
            OsuUserProfile(42, "Target", "US", "avatar", None, None),
            (_play(9001), _play(9002), _play(9003)),
        )

    async def test_frozen_defaults_and_request_accounting(self) -> None:
        refresh = AsyncMock(return_value=self.target)
        ranking = AsyncMock(return_value=self.ranking)
        client = object()
        result = await generate_recommendations(
            " target ", limit=1, osu_client=client,  # type: ignore[arg-type]
            refresh_function=refresh, ranking_function=ranking,
        )
        refresh.assert_awaited_once_with("target", client)
        ranking.assert_awaited_once_with(
            "Target", seed_count=SEED_COUNT, hydration_budget=HYDRATION_BUDGET,
            top_plays=CANDIDATE_TOP_PLAYS, osu_client=client,
        )
        self.assertEqual((SEED_COUNT, HYDRATION_BUDGET), (5, 25))
        self.assertEqual((RANKING_PLAYER_LIMIT, DISCOVERY_PLAYER_LIMIT), (10, 15))
        self.assertEqual(result.requests.profile_requests, 1)
        self.assertEqual(result.requests.target_top_play_requests, 1)
        self.assertEqual(result.requests.leaderboard_requests, 5)
        self.assertEqual(result.requests.candidate_top_play_requests, 25)

    async def test_limit_is_applied_after_complete_ordering(self) -> None:
        refresh = AsyncMock(return_value=self.target)
        ranking = AsyncMock(return_value=self.ranking)
        with patch(
            "backend.app.recommendation.service.build_hybrid_ranking",
            return_value=build_hybrid_ranking(
                self.ranking,
                _recovery().target_preference_profile,
            ),
        ):
            ten = await generate_recommendations(
                "Target", limit=1, osu_client=object(),  # type: ignore[arg-type]
                refresh_function=refresh, ranking_function=ranking,
            )
            twenty = await generate_recommendations(
                "Target", limit=2, osu_client=object(),  # type: ignore[arg-type]
                refresh_function=refresh, ranking_function=ranking,
            )
        self.assertEqual(ten.recommendations, twenty.recommendations[:1])
        self.assertEqual(ten.recommendations[0].why_recommended,
                         "Recommended by 2 similar players. "
                         "Star rating, AR, and BPM are within your usual range.")

    async def test_service_validates_limit(self) -> None:
        for limit in (0, 101):
            with self.assertRaises(ValueError):
                await generate_recommendations("Target", limit=limit)


class RecommendationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_route_delegates_and_serializes(self) -> None:
        result = RecommendationResult(
            "Target", 42, (),
            RecommendationContext(100, 25, 10, 15, 500, 0),
            RecommendationRequestAccounting(1, 1, 5, 25),
        )
        with patch(
            "backend.app.recommendations.generate_recommendations",
            new=AsyncMock(return_value=result),
        ) as service:
            response = self.client.get("/api/recommendations/Target?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["target_user_id"], 42)
        service.assert_awaited_once_with("Target", limit=1)

    def test_http_limit_bounds(self) -> None:
        self.assertEqual(self.client.get("/api/recommendations/x?limit=0").status_code, 422)
        self.assertEqual(self.client.get("/api/recommendations/x?limit=101").status_code, 422)
        result = RecommendationResult(
            "x", 1, (), RecommendationContext(0, 0, 0, 0, 0, 0),
            RecommendationRequestAccounting(1, 1, 0, 0),
        )
        with patch(
            "backend.app.recommendations.generate_recommendations",
            new=AsyncMock(return_value=result),
        ):
            self.assertEqual(self.client.get("/api/recommendations/x?limit=1").status_code, 200)
            self.assertEqual(self.client.get("/api/recommendations/x?limit=100").status_code, 200)

    def test_upstream_failure_is_not_an_empty_success(self) -> None:
        with patch(
            "backend.app.recommendations.generate_recommendations",
            new=AsyncMock(side_effect=OsuNetworkError("private detail")),
        ):
            response = self.client.get("/api/recommendations/Target")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "The osu! API is currently unreachable."}
        )
        self.assertNotIn("private detail", response.text)


def _play(beatmap_id: int) -> OsuTopPlay:
    return OsuTopPlay(
        None, beatmap_id, None, None, None, None, None, None, None, (), None,
        None, 5.0, 9.0, 180.0,
    )


def _id(item: object) -> int:
    return item.preference_evidence.collaborative.candidate_map.beatmap_id  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()

"""Focused tests for the production recommendation service."""

import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, call, patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.osu.client import OsuBeatmapDifficultyAttributes, OsuTopPlay, OsuUserProfile
from backend.app.osu.client import OsuNetworkError
from backend.app.recommendation.candidate_maps import CandidateMapSupport
from backend.app.recommendation.service import (
    CANDIDATE_TOP_PLAYS,
    DISCOVERY_PLAYER_LIMIT,
    HYDRATION_BUDGET,
    RANKING_PLAYER_LIMIT,
    SEED_COUNT,
    RecommendationContext,
    RecommendationRequestAccounting,
    RecommendationPreferences,
    RecommendationResult,
    TargetRecommendationProfile,
    RefreshedTarget,
    build_hybrid_ranking,
    enrich_adjusted_stars,
    generate_recommendations,
    suggested_mod_combination,
    _supporting_players,
    _target_recommendation_profile,
)
from backend.tests.test_selection_expansion_analysis import _preference, _recovery


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

    def test_suggested_mod_mode_tie_and_nm(self) -> None:
        hdhr = _support(("HD", "HR"), 3)
        hddt = _support(("HD", "DT"), 1)
        self.assertEqual(
            suggested_mod_combination((hdhr, hdhr, hddt)), ("HD", "HR")
        )
        self.assertEqual(suggested_mod_combination((hdhr, hddt)), ("HD", "DT"))
        self.assertEqual(suggested_mod_combination((_support((), 1),)), ())

    def test_hybrid_mods_keep_native_evidence_and_allow_discovery_evidence(self) -> None:
        players = list(self.ranking.candidates)
        players[0] = replace(
            players[0],
            hydrated_top_plays=tuple(
                replace(play, mods=("HD", "HR")) for play in players[0].hydrated_top_plays
            ),
        )
        players[11] = replace(
            players[11],
            hydrated_top_plays=tuple(
                replace(play, mods=("HD", "DT")) for play in players[11].hydrated_top_plays
            ),
        )
        ordered = build_hybrid_ranking(
            replace(self.ranking, candidates=tuple(players)), self.profile
        )
        by_id = {_id(item): item for item in ordered}
        native = by_id[101].preference_evidence.collaborative.candidate_map
        discovery = by_id[105].preference_evidence.collaborative.candidate_map
        self.assertEqual(suggested_mod_combination(native.supports), ("HD", "HR"))
        self.assertEqual(suggested_mod_combination(discovery.supports), ("HD", "DT"))

    def test_supporting_players_are_complete_ordered_and_deterministic(self) -> None:
        supports = (
            _support(("HD", "HR"), 3, user_id=30, username="third"),
            _support((), 1, user_id=10, username="first"),
            _support(("HD",), 2, user_id=20, username="second"),
        )
        first = _supporting_players(supports)
        second = _supporting_players(supports)
        self.assertEqual(first, second)
        self.assertEqual([item.user_id for item in first], [10, 20, 30])
        self.assertEqual([item.similarity_rank for item in first], [1, 2, 3])
        self.assertEqual([item.mods for item in first], [(), ("HD",), ("HD", "HR")])
        self.assertEqual(len(first), len(supports))

    def test_hybrid_support_details_preserve_native_and_discovery_isolation(self) -> None:
        ordered = build_hybrid_ranking(self.ranking, self.profile)
        by_id = {_id(item): item for item in ordered}
        native = by_id[101].preference_evidence.collaborative.candidate_map
        discovery = by_id[105].preference_evidence.collaborative.candidate_map
        self.assertEqual(
            [item.user_id for item in _supporting_players(native.supports)],
            [support.user_id for support in native.supports],
        )
        self.assertNotIn(
            self.ranking.candidates[12].user_id,
            [item.user_id for item in _supporting_players(native.supports)],
        )
        self.assertIn(
            self.ranking.candidates[11].user_id,
            [item.user_id for item in _supporting_players(discovery.supports)],
        )


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
        self.assertEqual(result.requests.beatmap_attribute_requests, 0)
        self.assertIsNone(result.preferences.star_rating)

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
        self.assertEqual(
            len(ten.recommendations[0].supporting_players),
            ten.recommendations[0].support_count,
        )
        self.assertEqual(ten.recommendations[0].why_recommended,
                         "Recommended by 2 similar players. "
                         "Base AR and base BPM are within your usual range.")

    async def test_service_validates_limit(self) -> None:
        for limit in (0, 101):
            with self.assertRaises(ValueError):
                await generate_recommendations("Target", limit=limit)

    async def test_adjusted_star_mapping_failure_and_request_count(self) -> None:
        base = _preference(100, 1)
        candidate = base.preference_evidence.collaborative.candidate_map
        modded = replace(candidate, supports=(_support(("HD", "HR"), 1),))
        nm = replace(candidate, beatmap_id=101, supports=(_support((), 1),))
        items = (
            replace(base, preference_evidence=replace(
                base.preference_evidence,
                collaborative=replace(base.preference_evidence.collaborative, candidate_map=modded),
            )),
            replace(base, preference_evidence=replace(
                base.preference_evidence,
                collaborative=replace(base.preference_evidence.collaborative, candidate_map=nm),
            )),
        )
        client = AsyncMock()
        client.get_beatmap_difficulty_attributes.return_value = (
            OsuBeatmapDifficultyAttributes(6.25)
        )
        values, requests = await enrich_adjusted_stars(items, ("HD", "HR"), client)
        self.assertEqual((values[100], values[101], requests), (6.25, 6.25, 2))
        self.assertEqual(list(values), [_id(item) for item in items])
        self.assertEqual(
            client.get_beatmap_difficulty_attributes.await_args_list,
            [call(100, ("HD", "HR")), call(101, ("HD", "HR"))],
        )
        client.get_beatmap_difficulty_attributes.side_effect = OsuNetworkError("down")
        values, requests = await enrich_adjusted_stars(items[:1], ("HD", "HR"), client)
        self.assertEqual((values[100], requests), (None, 1))

    async def test_target_mods_control_suggestion_and_star_not_supporter_mods(self) -> None:
        refresh = AsyncMock(return_value=self.target)
        ranking = AsyncMock(return_value=self.ranking)
        client = AsyncMock()
        client.get_beatmap_difficulty_attributes.return_value = OsuBeatmapDifficultyAttributes(5.75)
        target = replace(
            self.target,
            top_plays=tuple(replace(play, mods=("HD", "HR")) for play in self.target.top_plays),
        )
        refresh.return_value = target
        result = await generate_recommendations(
            "Target", limit=1, osu_client=client,
            refresh_function=refresh, ranking_function=ranking,
        )
        self.assertEqual(result.target_profile.primary_mods, ("HD", "HR"))
        self.assertEqual(result.recommendations[0].suggested_mods, ("HD", "HR"))
        self.assertEqual(result.recommendations[0].adjusted_star_rating, 5.75)
        client.get_beatmap_difficulty_attributes.assert_awaited_once_with(
            result.recommendations[0].beatmap_id, ("HD", "HR")
        )
        self.assertEqual(result.preferences.star_rating, None)

    def test_target_mod_profile_counts_shares_tie_and_pp_bounds(self) -> None:
        plays = (
            replace(_play(1), mods=("HD", "HR"), performance_points=100.0),
            replace(_play(2), mods=("HD",), performance_points=200.0),
            replace(_play(3), mods=("HD", "HR"), performance_points=300.0),
            replace(_play(4), mods=("HD",), performance_points=400.0),
        )
        profile = _target_recommendation_profile(replace(self.target, top_plays=plays))
        self.assertEqual(profile.primary_mods, ("HD",))
        self.assertEqual(
            [(item.mods, item.count, item.share) for item in profile.mod_distribution],
            [(('HD',), 2, 0.5), (('HD', 'HR'), 2, 0.5)],
        )
        self.assertEqual(profile.performance_points, _bounds(175.0, 250.0, 325.0))
        self.assertIsNone(profile.actual_play_star_rating)


class RecommendationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_route_delegates_and_serializes(self) -> None:
        result = RecommendationResult(
            "Target", 42, (),
            RecommendationContext(100, 25, 10, 15, 500, 0),
            RecommendationRequestAccounting(1, 1, 5, 25, 3),
            RecommendationPreferences(None, None, None),
            TargetRecommendationProfile((), (), None, None), (),
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
            RecommendationRequestAccounting(1, 1, 0, 0, 0),
            RecommendationPreferences(None, None, None),
            TargetRecommendationProfile((), (), None, None), (),
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


def _support(
    mods: tuple[str, ...],
    rank: int,
    *,
    user_id: int | None = None,
    username: str | None = None,
) -> CandidateMapSupport:
    resolved_id = rank if user_id is None else user_id
    resolved_name = f"p{rank}" if username is None else username
    return CandidateMapSupport(
        resolved_id, resolved_name, rank, 1, 0.1, 0.1, mods, None
    )


def _bounds(first: float, middle: float, third: float):
    from backend.app.recommendation.service import PreferenceBounds
    return PreferenceBounds(first, middle, third)


if __name__ == "__main__":
    unittest.main()

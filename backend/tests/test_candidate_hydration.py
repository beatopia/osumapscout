"""Tests for bounded, ephemeral candidate top-play hydration."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.candidates.discovery import (
    CandidateDiscoveryResult,
    CandidateTargetNotFoundError,
    CandidateUser,
)
from backend.app.candidates.hydration import (
    CandidateHydrationError,
    hydrate_candidate_top_plays,
)
from backend.app.osu.client import OsuApiError, OsuTopPlay


class CandidateHydrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_discovery_and_preserves_order_provenance_and_counts(self) -> None:
        discovery = AsyncMock(
            return_value=self._discovery(
                [
                    CandidateUser(30, "First", ("local",)),
                    CandidateUser(10, "Second", ("local", "ranking")),
                    CandidateUser(20, "Third", ("ranking",)),
                ],
                ranking_requests=2,
            )
        )
        client = self._client(
            [[self._play(301)], [self._play(101), self._play(102)]]
        )

        result = await hydrate_candidate_top_plays(
            "target",
            candidate_pool_limit=20,
            hydrate_limit=2,
            top_plays_per_candidate=25,
            discovery_function=discovery,
            osu_client=client,
        )

        discovery.assert_awaited_once_with("target", limit=20, osu_client=client)
        self.assertEqual(
            [candidate.user_id for candidate in result.hydrated_candidates],
            [30, 10],
        )
        self.assertEqual(
            [candidate.sources for candidate in result.hydrated_candidates],
            [("local",), ("local", "ranking")],
        )
        self.assertEqual(result.discovered_candidate_count, 3)
        self.assertEqual(result.ranking_requests_made, 2)
        self.assertEqual(result.top_play_requests_made, 2)
        self.assertEqual(
            client.get_top_plays_by_user_id.await_args_list[0].args,
            (30,),
        )
        self.assertEqual(
            client.get_top_plays_by_user_id.await_args_list[0].kwargs,
            {"limit": 25},
        )
        self.assertEqual(
            client.get_top_plays_by_user_id.await_args_list[1].args,
            (10,),
        )

    async def test_smaller_discovered_pool_and_zero_play_candidate_succeed(self) -> None:
        discovery = AsyncMock(
            return_value=self._discovery(
                [CandidateUser(10, "Only", ("ranking",))],
                ranking_requests=3,
            )
        )
        client = self._client([[]])

        result = await hydrate_candidate_top_plays(
            "target",
            hydrate_limit=10,
            discovery_function=discovery,
            osu_client=client,
        )

        self.assertEqual(len(result.hydrated_candidates), 1)
        self.assertEqual(result.hydrated_candidates[0].top_plays, ())
        self.assertEqual(result.top_play_requests_made, 1)
        self.assertEqual(result.ranking_requests_made, 3)

    async def test_zero_candidates_returns_without_credentials_or_osu_calls(self) -> None:
        discovery = AsyncMock(return_value=self._discovery([], ranking_requests=1))

        with patch.dict(os.environ, {}, clear=True):
            result = await hydrate_candidate_top_plays(
                "target",
                discovery_function=discovery,
            )

        self.assertEqual(result.hydrated_candidates, ())
        self.assertEqual(result.top_play_requests_made, 0)
        self.assertEqual(result.ranking_requests_made, 1)

    async def test_candidates_require_credentials_when_client_not_injected(self) -> None:
        discovery = AsyncMock(
            return_value=self._discovery([CandidateUser(10, "Player", ("local",))])
        )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OSU_CLIENT_ID"):
                await hydrate_candidate_top_plays(
                    "target",
                    discovery_function=discovery,
                )

    async def test_upstream_failure_raises_hydration_error_without_partial_result(self) -> None:
        discovery = AsyncMock(
            return_value=self._discovery(
                [
                    CandidateUser(10, "First", ("local",)),
                    CandidateUser(20, "Second", ("ranking",)),
                ]
            )
        )
        client = self._client([[self._play(101)], OsuApiError("safe failure")])

        with self.assertRaisesRegex(CandidateHydrationError, "candidate user 20"):
            await hydrate_candidate_top_plays(
                "target",
                hydrate_limit=2,
                discovery_function=discovery,
                osu_client=client,
            )

        self.assertEqual(client.get_top_plays_by_user_id.await_count, 2)

    async def test_missing_target_from_discovery_is_preserved(self) -> None:
        discovery = AsyncMock(
            side_effect=CandidateTargetNotFoundError("target was not found")
        )

        with self.assertRaisesRegex(CandidateTargetNotFoundError, "not found"):
            await hydrate_candidate_top_plays(
                "target",
                discovery_function=discovery,
            )

    async def test_all_limits_are_validated_before_discovery(self) -> None:
        discovery = AsyncMock()
        invalid_cases = (
            {"candidate_pool_limit": 0},
            {"candidate_pool_limit": 101},
            {"hydrate_limit": 0},
            {"hydrate_limit": 11},
            {"top_plays_per_candidate": 0},
            {"top_plays_per_candidate": 101},
            {"hydrate_limit": True},
        )

        for arguments in invalid_cases:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, "must be an integer"):
                    await hydrate_candidate_top_plays(
                        "target",
                        discovery_function=discovery,
                        **arguments,
                    )

        discovery.assert_not_awaited()

    async def test_does_not_use_profile_lookup_or_persistence(self) -> None:
        discovery = AsyncMock(
            return_value=self._discovery([CandidateUser(10, "Player", ("local",))])
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(return_value=[]),
            get_user_by_username=AsyncMock(),
            get_top_plays_by_username=AsyncMock(),
        )

        with patch(
            "backend.app.database.persistence.persist_user_top_plays"
        ) as persist:
            await hydrate_candidate_top_plays(
                "target",
                discovery_function=discovery,
                osu_client=client,
            )

        client.get_top_plays_by_user_id.assert_awaited_once_with(10, limit=100)
        client.get_user_by_username.assert_not_awaited()
        client.get_top_plays_by_username.assert_not_awaited()
        persist.assert_not_called()

    @staticmethod
    def _discovery(
        candidates: list[CandidateUser],
        ranking_requests: int = 0,
    ) -> CandidateDiscoveryResult:
        return CandidateDiscoveryResult(
            target_user_id=42,
            target_username="Target",
            requested_count=20,
            candidates=tuple(candidates),
            ranking_requests_made=ranking_requests,
        )

    @staticmethod
    def _client(results: list[object]) -> SimpleNamespace:
        return SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(side_effect=results),
        )

    @staticmethod
    def _play(beatmap_id: int) -> OsuTopPlay:
        return OsuTopPlay(
            score_id=beatmap_id + 1000,
            beatmap_id=beatmap_id,
            beatmapset_id=None,
            artist=None,
            title=None,
            difficulty_name=None,
            performance_points=None,
            accuracy=None,
            grade=None,
            mods=(),
            max_combo=None,
            played_at=None,
            star_rating=None,
            approach_rate=None,
            bpm=None,
        )


if __name__ == "__main__":
    unittest.main()

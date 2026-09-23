"""Tests for target-map candidate overlap evaluation."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapCandidateExperiment,
    TargetMapSeed,
)
from backend.app.osu.client import OsuApiError, OsuTopPlay
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
    calculate_overlap_similarity,
)
from backend.app.similarity.target_map_overlap import (
    SeedExcludedTargetEmptyError,
    calculate_raw_and_seed_excluded_overlap,
    evaluate_target_map_candidates,
)


class FakeTargetOverlapSession:
    def __init__(self, target: Any, beatmap_ids: list[int]) -> None:
        self.target = target
        self.beatmap_ids = beatmap_ids
        self.execute_calls = 0

    def __enter__(self) -> "FakeTargetOverlapSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        self.execute_calls += 1
        if self.execute_calls == 1:
            return SimpleNamespace(one_or_none=lambda: self.target)
        if self.execute_calls == 2:
            rows = [SimpleNamespace(beatmap_id=value) for value in self.beatmap_ids]
            return SimpleNamespace(all=lambda: rows)
        raise AssertionError("Target-map overlap performed an unexpected query.")


class LeakageMetricTests(unittest.TestCase):
    def test_seed_only_overlap_disappears(self) -> None:
        metrics = calculate_raw_and_seed_excluded_overlap(
            [1, 2, 3, 4, 5],
            [1, 2, 8, 9],
            [1, 2],
        )

        self.assertEqual(metrics.raw.shared_beatmap_count, 2)
        self.assertEqual(metrics.seed_excluded.shared_beatmap_count, 0)
        self.assertEqual(metrics.seed_excluded.jaccard_similarity, 0.0)
        self.assertEqual(metrics.seed_excluded.target_coverage, 0.0)

    def test_independent_overlap_remains_after_seed_removal(self) -> None:
        metrics = calculate_raw_and_seed_excluded_overlap(
            [1, 2, 3, 4, 5],
            [1, 2, 4, 9],
            [1, 2],
        )

        self.assertEqual(metrics.raw.shared_beatmap_count, 3)
        self.assertEqual(metrics.seed_excluded.shared_beatmap_count, 1)
        self.assertAlmostEqual(metrics.seed_excluded.jaccard_similarity, 1 / 4)
        self.assertAlmostEqual(metrics.seed_excluded.target_coverage, 1 / 3)

    def test_duplicates_do_not_double_count_and_empty_candidate_is_valid(self) -> None:
        duplicate = calculate_raw_and_seed_excluded_overlap(
            [1, 1, 2, 3],
            [1, 1, 3, 3],
            [1],
        )
        empty = calculate_raw_and_seed_excluded_overlap([1, 2], [], [1])

        self.assertEqual(duplicate.raw.shared_beatmap_count, 2)
        self.assertEqual(duplicate.seed_excluded.shared_beatmap_count, 1)
        self.assertEqual(empty.raw.shared_beatmap_count, 0)
        self.assertEqual(empty.seed_excluded.shared_beatmap_count, 0)

    def test_seed_exclusion_cannot_empty_target(self) -> None:
        with self.assertRaisesRegex(SeedExcludedTargetEmptyError, "no target"):
            calculate_raw_and_seed_excluded_overlap([1, 2], [1], [1, 2])

    def test_existing_t0020_helper_is_called_twice(self) -> None:
        with patch(
            "backend.app.similarity.target_map_overlap.calculate_overlap_similarity",
            wraps=calculate_overlap_similarity,
        ) as overlap:
            calculate_raw_and_seed_excluded_overlap([1, 2], [1], [1])

        self.assertEqual(overlap.call_count, 2)


class TargetMapOverlapWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_acquisition_and_hydrates_numeric_ids_sequentially(self) -> None:
        session = self._session([1, 2, 3, 4, 5])
        acquisition = AsyncMock(
            return_value=self._acquisition(
                [
                    TargetMapCandidate(20, "Twenty", (1, 2)),
                    TargetMapCandidate(10, "Ten", (1,)),
                    TargetMapCandidate(30, "Thirty", (2,)),
                ],
                seeds=(TargetMapSeed(1, 1), TargetMapSeed(2, 2)),
                unique_count=50,
                requests=2,
            )
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(
                side_effect=[self._plays([1, 2, 4]), self._plays([1, 5])]
            ),
            get_user_by_username=AsyncMock(),
        )

        result = await evaluate_target_map_candidates(
            "target",
            seed_count=2,
            candidate_limit=30,
            hydrate_limit=2,
            top_plays=5,
            session_factory=lambda: session,
            acquisition_function=acquisition,
            osu_client=client,
        )

        acquisition.assert_awaited_once_with(
            "target", seed_count=2, candidate_limit=30, osu_client=client
        )
        self.assertEqual(
            [call.args[0] for call in client.get_top_plays_by_user_id.await_args_list],
            [20, 10],
        )
        self.assertTrue(
            all(call.kwargs == {"limit": 5} for call in client.get_top_plays_by_user_id.await_args_list)
        )
        client.get_user_by_username.assert_not_awaited()
        self.assertEqual(result.discovered_candidate_count, 50)
        self.assertEqual(result.leaderboard_requests_made, 2)
        self.assertEqual(result.top_play_requests_made, 2)
        self.assertEqual(result.selected_seeds, (TargetMapSeed(1, 1), TargetMapSeed(2, 2)))

    async def test_candidate_shortage_and_zero_plays_succeed(self) -> None:
        session = self._session([1, 2])
        acquisition = AsyncMock(
            return_value=self._acquisition(
                [TargetMapCandidate(10, "Ten", (1,))],
                seeds=(TargetMapSeed(1, 1),),
            )
        )
        client = SimpleNamespace(get_top_plays_by_user_id=AsyncMock(return_value=[]))

        result = await evaluate_target_map_candidates(
            "target",
            hydrate_limit=20,
            session_factory=lambda: session,
            acquisition_function=acquisition,
            osu_client=client,
        )

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].candidate_play_count, 0)
        self.assertEqual(result.candidates[0].raw_shared_beatmap_count, 0)
        self.assertEqual(result.candidates[0].seed_excluded_shared_beatmap_count, 0)
        self.assertEqual(result.top_play_requests_made, 1)

    async def test_ordering_uses_independent_overlap_then_seed_hits_then_id(self) -> None:
        session = self._session([1, 2, 3, 4, 5])
        candidates = [
            TargetMapCandidate(40, "Zero", (1, 2, 3)),
            TargetMapCandidate(30, "LowerJaccard", (1, 2)),
            TargetMapCandidate(20, "TieHighId", (1, 2)),
            TargetMapCandidate(10, "TieLowId", (1, 2)),
            TargetMapCandidate(50, "ZeroFewerSeeds", (1,)),
        ]
        acquisition = AsyncMock(
            return_value=self._acquisition(
                candidates,
                seeds=(TargetMapSeed(1, 1),),
            )
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(
                side_effect=[
                    self._plays([1]),
                    self._plays([1, 2, 3, 8, 9]),
                    self._plays([1, 2, 3, 8]),
                    self._plays([1, 2, 3, 9]),
                    self._plays([1]),
                ]
            )
        )

        result = await evaluate_target_map_candidates(
            "target",
            hydrate_limit=5,
            session_factory=lambda: session,
            acquisition_function=acquisition,
            osu_client=client,
        )

        self.assertEqual(
            [item.user_id for item in result.candidates],
            [10, 20, 30, 40, 50],
        )
        self.assertEqual(len(result.candidates), 5)

    async def test_target_empty_fails_before_acquisition_or_api(self) -> None:
        session = self._session([])
        acquisition = AsyncMock()
        client = SimpleNamespace(get_top_plays_by_user_id=AsyncMock())

        with self.assertRaisesRegex(TargetTopPlaysEmptyError, "no top plays"):
            await evaluate_target_map_candidates(
                "target",
                session_factory=lambda: session,
                acquisition_function=acquisition,
                osu_client=client,
            )

        acquisition.assert_not_awaited()
        client.get_top_plays_by_user_id.assert_not_awaited()

    async def test_missing_target_fails_before_external_work(self) -> None:
        session = FakeTargetOverlapSession(None, [])
        acquisition = AsyncMock()

        with self.assertRaisesRegex(SimilarityTargetNotFoundError, "was not found"):
            await evaluate_target_map_candidates(
                "missing",
                session_factory=lambda: session,
                acquisition_function=acquisition,
            )

        acquisition.assert_not_awaited()

    async def test_seed_exclusion_empty_fails_before_hydration(self) -> None:
        session = self._session([1, 2])
        acquisition = AsyncMock(
            return_value=self._acquisition(
                [TargetMapCandidate(10, "Ten", (1, 2))],
                seeds=(TargetMapSeed(1, 1), TargetMapSeed(2, 2)),
            )
        )
        client = SimpleNamespace(get_top_plays_by_user_id=AsyncMock())

        with self.assertRaisesRegex(SeedExcludedTargetEmptyError, "no target"):
            await evaluate_target_map_candidates(
                "target",
                session_factory=lambda: session,
                acquisition_function=acquisition,
                osu_client=client,
            )

        client.get_top_plays_by_user_id.assert_not_awaited()

    async def test_upstream_hydration_failure_has_no_partial_result(self) -> None:
        session = self._session([1, 2])
        acquisition = AsyncMock(
            return_value=self._acquisition(
                [TargetMapCandidate(10, "Ten", (1,))],
                seeds=(TargetMapSeed(1, 1),),
            )
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(side_effect=OsuApiError("failed"))
        )

        with self.assertRaisesRegex(CandidateHydrationError, "candidate user 10"):
            await evaluate_target_map_candidates(
                "target",
                session_factory=lambda: session,
                acquisition_function=acquisition,
                osu_client=client,
            )

    async def test_bounds_validate_before_io(self) -> None:
        session = self._session([1])
        acquisition = AsyncMock()
        for arguments in (
            {"seed_count": 0},
            {"seed_count": 11},
            {"candidate_limit": 0},
            {"candidate_limit": 101},
            {"hydrate_limit": 0},
            {"hydrate_limit": 21},
            {"top_plays": 0},
            {"top_plays": 101},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, "must be an integer"):
                    await evaluate_target_map_candidates(
                        "target",
                        session_factory=lambda: session,
                        acquisition_function=acquisition,
                        **arguments,
                    )
        self.assertEqual(session.execute_calls, 0)
        acquisition.assert_not_awaited()

    async def test_no_persistence_or_ranking_discovery(self) -> None:
        session = self._session([1, 2])
        acquisition = AsyncMock(
            return_value=self._acquisition([], seeds=(TargetMapSeed(1, 1),))
        )

        with (
            patch("backend.app.candidates.discovery.discover_candidate_users") as ranking,
            patch("backend.app.database.persistence.persist_user_top_plays") as persist,
        ):
            result = await evaluate_target_map_candidates(
                "target",
                session_factory=lambda: session,
                acquisition_function=acquisition,
            )

        self.assertEqual(result.candidates, ())
        ranking.assert_not_called()
        persist.assert_not_called()

    @staticmethod
    def _session(beatmap_ids: list[int]) -> FakeTargetOverlapSession:
        return FakeTargetOverlapSession(
            SimpleNamespace(user_id=42, username="Target"), beatmap_ids
        )

    @staticmethod
    def _acquisition(
        candidates: list[TargetMapCandidate],
        *,
        seeds: tuple[TargetMapSeed, ...],
        unique_count: int | None = None,
        requests: int = 1,
    ) -> TargetMapCandidateExperiment:
        return TargetMapCandidateExperiment(
            target_user_id=42,
            target_username="Target",
            selected_seeds=seeds,
            candidates=tuple(candidates),
            unique_candidate_count=(
                len(candidates) if unique_count is None else unique_count
            ),
            seed_hit_distribution=(),
            leaderboard_requests_made=requests,
        )

    @staticmethod
    def _plays(beatmap_ids: list[int]) -> list[OsuTopPlay]:
        return [TargetMapOverlapWorkflowTests._play(value) for value in beatmap_ids]

    @staticmethod
    def _play(beatmap_id: int) -> OsuTopPlay:
        return OsuTopPlay(
            score_id=None,
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

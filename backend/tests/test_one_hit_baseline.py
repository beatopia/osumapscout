"""Tests for the recurring-versus-one-hit overlap baseline."""

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
from backend.app.similarity.one_hit_baseline import (
    BaselineCandidatesEmptyError,
    evaluate_one_hit_baseline,
    select_stratified_one_hit_candidates,
    summarize_independent_overlap,
)
from backend.app.similarity.overlap import TargetTopPlaysEmptyError
from backend.app.similarity.target_map_overlap import (
    TargetMapCandidateOverlap,
    calculate_raw_and_seed_excluded_overlap,
)


class FakeBaselineSession:
    def __init__(self, beatmap_ids: list[int]) -> None:
        self.target = SimpleNamespace(user_id=42, username="Target")
        self.beatmap_ids = beatmap_ids
        self.execute_calls = 0

    def __enter__(self) -> "FakeBaselineSession":
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
        raise AssertionError("Baseline performed an unexpected database query.")


class OneHitSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seeds = (
            TargetMapSeed(1, 101),
            TargetMapSeed(50, 202),
            TargetMapSeed(100, 303),
        )

    def test_round_robin_prevents_first_seed_from_dominating(self) -> None:
        candidates = (
            self._candidate(1, 101),
            self._candidate(2, 101),
            self._candidate(3, 101),
            self._candidate(4, 202),
            self._candidate(5, 202),
            self._candidate(6, 303),
        )

        result = select_stratified_one_hit_candidates(candidates, self.seeds, 5)

        self.assertEqual([item.user_id for item in result], [1, 4, 6, 2, 5])
        self.assertTrue(all(item.seed_hit_count == 1 for item in result))

    def test_is_deterministic_deduplicated_and_skips_recurring_users(self) -> None:
        duplicate = self._candidate(1, 101)
        candidates = (
            duplicate,
            TargetMapCandidate(9, "Recurring", (101, 202)),
            duplicate,
            self._candidate(2, 202),
        )

        first = select_stratified_one_hit_candidates(candidates, self.seeds, 10)
        second = select_stratified_one_hit_candidates(candidates, self.seeds, 10)

        self.assertEqual(first, second)
        self.assertEqual([item.user_id for item in first], [1, 2])

    def test_empty_buckets_and_shortage_are_valid(self) -> None:
        candidates = (self._candidate(1, 202), self._candidate(2, 202))

        result = select_stratified_one_hit_candidates(candidates, self.seeds, 5)

        self.assertEqual([item.user_id for item in result], [1, 2])

    @staticmethod
    def _candidate(user_id: int, seed_id: int) -> TargetMapCandidate:
        return TargetMapCandidate(user_id, f"User{user_id}", (seed_id,))


class GroupSummaryTests(unittest.TestCase):
    def test_thresholds_total_mean_median_and_maximum(self) -> None:
        summary = summarize_independent_overlap(
            tuple(
                self._overlap(index, value)
                for index, value in enumerate([0, 1, 2, 7], start=1)
            )
        )

        self.assertEqual(summary.evaluated_count, 4)
        self.assertEqual(summary.zero_shared_count, 1)
        self.assertEqual(summary.one_or_more_shared_count, 3)
        self.assertEqual(summary.two_or_more_shared_count, 2)
        self.assertEqual(summary.five_or_more_shared_count, 1)
        self.assertEqual(summary.total_shared_count, 10)
        self.assertEqual(summary.mean_shared_count, 2.5)
        self.assertEqual(summary.median_shared_count, 1.5)
        self.assertEqual(summary.maximum_shared_count, 7)

    def test_odd_median_and_empty_summary(self) -> None:
        odd = summarize_independent_overlap(
            (self._overlap(1, 1), self._overlap(2, 9), self._overlap(3, 3))
        )
        empty = summarize_independent_overlap(())

        self.assertEqual(odd.median_shared_count, 3.0)
        self.assertEqual(empty.evaluated_count, 0)
        self.assertEqual(empty.mean_shared_count, 0.0)
        self.assertEqual(empty.median_shared_count, 0.0)
        self.assertEqual(empty.maximum_shared_count, 0)

    @staticmethod
    def _overlap(user_id: int, shared: int) -> TargetMapCandidateOverlap:
        return TargetMapCandidateOverlap(
            user_id=user_id,
            username=None,
            seed_beatmap_ids=(1,),
            candidate_play_count=100,
            raw_shared_beatmap_count=shared + 1,
            raw_jaccard_similarity=0.0,
            raw_target_coverage=0.0,
            seed_excluded_shared_beatmap_count=shared,
            seed_excluded_jaccard_similarity=0.0,
            seed_excluded_target_coverage=0.0,
        )


class OneHitBaselineWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_separates_groups_hydrates_ids_and_reuses_metrics(self) -> None:
        session = FakeBaselineSession([1, 2, 3, 4])
        seeds = (TargetMapSeed(1, 1), TargetMapSeed(4, 4))
        acquisition = AsyncMock(
            return_value=self._acquisition(
                [
                    TargetMapCandidate(10, "Recurring", (1, 4)),
                    TargetMapCandidate(20, "OneA", (1,)),
                    TargetMapCandidate(30, "OneB", (4,)),
                    TargetMapCandidate(40, "OneA2", (1,)),
                ],
                seeds,
            )
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(
                side_effect=[self._plays([1, 2]), self._plays([1, 3]), self._plays([4])]
            ),
            get_user_by_username=AsyncMock(),
        )

        with patch(
            "backend.app.similarity.one_hit_baseline.calculate_raw_and_seed_excluded_overlap",
            wraps=calculate_raw_and_seed_excluded_overlap,
        ) as metrics:
            result = await evaluate_one_hit_baseline(
                "target",
                recurring_limit=1,
                one_hit_limit=2,
                top_plays=4,
                session_factory=lambda: session,
                acquisition_function=acquisition,
                osu_client=client,
            )

        acquisition.assert_awaited_once_with(
            "target",
            seed_count=5,
            candidate_limit=100,
            osu_client=client,
        )
        self.assertEqual(metrics.call_count, 3)
        self.assertEqual([item.user_id for item in result.recurring_candidates], [10])
        self.assertEqual([item.user_id for item in result.one_hit_candidates], [20, 30])
        self.assertTrue(
            all(item.seed_hit_count >= 2 for item in result.recurring_candidates)
        )
        self.assertTrue(
            all(item.seed_hit_count == 1 for item in result.one_hit_candidates)
        )
        self.assertEqual(
            result.recurring_candidates[0].raw_shared_beatmap_count,
            2,
        )
        self.assertEqual(
            result.recurring_candidates[0].seed_excluded_shared_beatmap_count,
            1,
        )
        self.assertEqual(
            result.one_hit_candidates[1].seed_excluded_shared_beatmap_count,
            0,
        )
        self.assertFalse(
            {item.user_id for item in result.recurring_candidates}
            & {item.user_id for item in result.one_hit_candidates}
        )
        self.assertEqual(
            [call.args[0] for call in client.get_top_plays_by_user_id.await_args_list],
            [10, 20, 30],
        )
        self.assertEqual(result.top_play_requests_made, 3)
        client.get_user_by_username.assert_not_awaited()

    async def test_missing_group_is_allowed_but_both_empty_fail(self) -> None:
        session = FakeBaselineSession([1, 2])
        one_hit_only = AsyncMock(
            return_value=self._acquisition(
                [TargetMapCandidate(20, "One", (1,))],
                (TargetMapSeed(1, 1),),
            )
        )
        client = SimpleNamespace(get_top_plays_by_user_id=AsyncMock(return_value=[]))

        result = await evaluate_one_hit_baseline(
            "target",
            session_factory=lambda: session,
            acquisition_function=one_hit_only,
            osu_client=client,
        )
        self.assertEqual(result.recurring_candidates, ())
        self.assertEqual(result.recurring_summary.evaluated_count, 0)
        self.assertEqual(len(result.one_hit_candidates), 1)

        recurring_session = FakeBaselineSession([1, 2])
        recurring_only = AsyncMock(
            return_value=self._acquisition(
                [TargetMapCandidate(10, "Recurring", (1, 2))],
                (TargetMapSeed(1, 1),),
            )
        )
        recurring_result = await evaluate_one_hit_baseline(
            "target",
            session_factory=lambda: recurring_session,
            acquisition_function=recurring_only,
            osu_client=client,
        )
        self.assertEqual(len(recurring_result.recurring_candidates), 1)
        self.assertEqual(recurring_result.one_hit_candidates, ())
        self.assertEqual(recurring_result.one_hit_summary.evaluated_count, 0)

        empty_session = FakeBaselineSession([1, 2])
        empty = AsyncMock(
            return_value=self._acquisition([], (TargetMapSeed(1, 1),))
        )
        with self.assertRaisesRegex(BaselineCandidatesEmptyError, "no recurring"):
            await evaluate_one_hit_baseline(
                "target",
                session_factory=lambda: empty_session,
                acquisition_function=empty,
                osu_client=client,
            )

    async def test_bounds_validate_before_database_or_acquisition(self) -> None:
        acquisition = AsyncMock()
        for keyword, value in (
            ("seed_count", 0),
            ("candidate_limit", 101),
            ("recurring_limit", 21),
            ("one_hit_limit", 0),
            ("top_plays", 101),
        ):
            with self.subTest(keyword=keyword):
                with self.assertRaises(ValueError):
                    await evaluate_one_hit_baseline(
                        "target",
                        session_factory=lambda: self.fail("database accessed"),
                        acquisition_function=acquisition,
                        **{keyword: value},
                    )
        acquisition.assert_not_awaited()

    async def test_empty_target_fails_before_acquisition(self) -> None:
        session = FakeBaselineSession([])
        acquisition = AsyncMock()

        with self.assertRaisesRegex(TargetTopPlaysEmptyError, "no top plays"):
            await evaluate_one_hit_baseline(
                "target",
                session_factory=lambda: session,
                acquisition_function=acquisition,
            )
        acquisition.assert_not_awaited()

    async def test_hydration_failure_returns_no_partial_result(self) -> None:
        session = FakeBaselineSession([1, 2])
        acquisition = AsyncMock(
            return_value=self._acquisition(
                [TargetMapCandidate(10, "Recurring", (1, 2))],
                (TargetMapSeed(1, 1),),
            )
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(side_effect=OsuApiError("failed"))
        )

        with self.assertRaisesRegex(CandidateHydrationError, "candidate user 10"):
            await evaluate_one_hit_baseline(
                "target",
                session_factory=lambda: session,
                acquisition_function=acquisition,
                osu_client=client,
            )

    async def test_no_ranking_discovery_or_persistence(self) -> None:
        session = FakeBaselineSession([1, 2])
        acquisition = AsyncMock(
            return_value=self._acquisition(
                [TargetMapCandidate(20, "One", (1,))],
                (TargetMapSeed(1, 1),),
            )
        )
        client = SimpleNamespace(get_top_plays_by_user_id=AsyncMock(return_value=[]))

        with (
            patch("backend.app.candidates.discovery.discover_candidate_users") as ranking,
            patch("backend.app.database.persistence.persist_user_top_plays") as persist,
        ):
            await evaluate_one_hit_baseline(
                "target",
                session_factory=lambda: session,
                acquisition_function=acquisition,
                osu_client=client,
            )
        ranking.assert_not_called()
        persist.assert_not_called()

    @staticmethod
    def _acquisition(
        candidates: list[TargetMapCandidate],
        seeds: tuple[TargetMapSeed, ...],
    ) -> TargetMapCandidateExperiment:
        return TargetMapCandidateExperiment(
            target_user_id=42,
            target_username="Target",
            selected_seeds=seeds,
            candidates=tuple(candidates),
            unique_candidate_count=len(candidates),
            seed_hit_distribution=(),
            leaderboard_requests_made=len(seeds),
        )

    @staticmethod
    def _plays(ids: list[int]) -> list[OsuTopPlay]:
        return [OneHitBaselineWorkflowTests._play(value) for value in ids]

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

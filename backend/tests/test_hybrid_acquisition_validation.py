"""Focused tests for the fixed T0054 validation comparison."""

import unittest
from dataclasses import replace
from unittest.mock import AsyncMock

from backend.app.candidates.target_maps import TargetMapCandidate, TargetMapCandidatePool, TargetMapSeed
from backend.app.recommendation.allocation_mixture_experiment import allocate_candidates, source_priority
from backend.app.recommendation.holdout_recovery import (
    HeldOutMapRecovery,
    OrderingRecoverySummary,
    RecoveredRankSummary,
    TargetPlayEvidence,
    calculate_split_position_sets,
)
from backend.app.recommendation.hybrid_acquisition_validation import (
    SignalObservation,
    VALIDATION_ALLOCATIONS,
    compare_number,
    recovery_id_sets,
    summarize_signal_groups,
)
from backend.app.recommendation.candidate_acquisition_experiment import HydrationCacheClient


class HybridValidationTests(unittest.TestCase):
    def test_only_fixed_baseline_and_20_5_views_exist(self) -> None:
        self.assertEqual(VALIDATION_ALLOCATIONS, (("25/0", 25, 0), ("20/5", 20, 5)))

    def test_baseline_and_hybrid_retain_t0053_identity(self) -> None:
        seeds = (TargetMapSeed(1, 10), TargetMapSeed(2, 20))
        candidates = tuple(
            TargetMapCandidate(value, str(value), (10, 20) if value < 8 else (10,))
            for value in range(1, 40)
        )
        priority = source_priority(TargetMapCandidatePool(99, "target", seeds, candidates, (), 2))
        baseline, _ = allocate_candidates(priority, (), 25, 0)
        hybrid, _ = allocate_candidates(priority, tuple(reversed(priority)), 20, 5)
        self.assertEqual([item.candidate.user_id for item in baseline], [item.user_id for item in priority[:25]])
        self.assertEqual(len({item.candidate.user_id for item in hybrid}), 25)
        self.assertEqual(sum(item.allocation_source == "target_mod" for item in hybrid), 5)

    def test_historical_and_new_splits_are_stable_and_deterministic(self) -> None:
        historical = calculate_split_position_sets(100, 10, 3)
        expanded = calculate_split_position_sets(100, 10, 8)
        repeated = calculate_split_position_sets(100, 10, 8)
        self.assertEqual(expanded, repeated)
        self.assertEqual(expanded.split_positions[:3], historical.split_positions)
        self.assertEqual(len(expanded.split_positions), 8)
        self.assertEqual(len(set(expanded.split_positions)), 8)

    def test_comparison_classifies_improvement_worsening_and_tie(self) -> None:
        self.assertEqual(compare_number(2, 1), "improved")
        self.assertEqual(compare_number(1, 2), "worsened")
        self.assertEqual(compare_number(1, 1), "tied")

    def test_transition_accounting_reports_new_lost_and_shared(self) -> None:
        def row(beatmap_id: int, rank: int | None) -> HeldOutMapRecovery:
            play = TargetPlayEvidence(beatmap_id, beatmap_id, None, None, None, None, None, None, ())
            return HeldOutMapRecovery(play, rank, rank, rank, None, None, None, None)
        newly, lost, shared = recovery_id_sets(
            (row(1, 10), row(2, 20), row(3, None)),
            (row(1, 5), row(2, None), row(3, 30)),
        )
        self.assertEqual(newly, {3})
        self.assertEqual(lost, {2})
        self.assertEqual(shared, {1})

    def test_signal_groups_calculate_known_means_and_medians(self) -> None:
        rows = (
            SignalObservation("improved", 2, .2, 4, 10, .5, 1, 2, 3),
            SignalObservation("improved", 4, .4, 8, 20, .7, 3, 4, 5),
            SignalObservation("worsened", 9, .9, 9, 9, .9, -1, -2, -3),
        )
        improved, worsened, tied = summarize_signal_groups(rows)
        self.assertEqual(improved.count, 2)
        expected = (3, .3, 6, 15, .6, 2, 3, 4)
        for actual, wanted in zip(improved.means, expected, strict=True):
            self.assertAlmostEqual(actual, wanted)
        for actual, wanted in zip(improved.medians, expected, strict=True):
            self.assertAlmostEqual(actual, wanted)
        self.assertEqual(worsened.count, 1)
        self.assertEqual(tied.count, 0)

    def test_recovered_rank_summary_is_not_reinterpreted(self) -> None:
        summary = OrderingRecoverySummary(10, 2, .2, 1, 1, 2, 2, .1, .1, .2, .2, RecoveredRankSummary(4, 8, 8, 12))
        same = replace(summary)
        self.assertEqual(same, summary)


class SharedHydrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_view_duplicate_is_hydrated_once(self) -> None:
        client = AsyncMock()
        client.get_top_plays_by_user_id.return_value = []
        cache = HydrationCacheClient(client)
        await cache.get_top_plays_by_user_id(42, 100)
        await cache.get_top_plays_by_user_id(42, 100)
        self.assertEqual(cache.actual_top_play_requests, 1)


if __name__ == "__main__":
    unittest.main()

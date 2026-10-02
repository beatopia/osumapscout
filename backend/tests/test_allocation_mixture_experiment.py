"""Focused tests for T0053 budget-neutral allocations."""

import unittest
from collections.abc import Iterable
from unittest.mock import AsyncMock

from backend.app.candidates.target_maps import TargetMapCandidate, TargetMapCandidatePool, TargetMapSeed
from backend.app.recommendation.allocation_mixture_experiment import (
    ALLOCATIONS,
    allocate_candidates,
    source_priority,
)
from backend.app.recommendation.candidate_acquisition_experiment import HydrationCacheClient


class AllocationConstructionTests(unittest.IsolatedAsyncioTestCase):
    def test_20_5_allocation_is_budget_neutral(self) -> None:
        selected, accounting = allocate_candidates(
            self._candidates(range(1, 31)), self._candidates(range(101, 131)), 20, 5
        )
        self.assertEqual(len(selected), 25)
        self.assertEqual([item.allocation_source for item in selected].count("baseline"), 20)
        self.assertEqual([item.allocation_source for item in selected].count("target_mod"), 5)
        self.assertEqual(accounting.final_unique, 25)

    def test_cross_source_duplicates_are_hydrated_once(self) -> None:
        selected, accounting = allocate_candidates(
            self._candidates(range(1, 26)), self._candidates(range(18, 40)), 20, 5
        )
        ids = [item.candidate.user_id for item in selected]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[-5:], [21, 22, 23, 24, 25])
        self.assertEqual(accounting.duplicates_skipped, 3)

    def test_target_mod_shortage_backfills_from_baseline(self) -> None:
        selected, accounting = allocate_candidates(
            self._candidates(range(1, 31)), self._candidates((1, 2)), 20, 5
        )
        self.assertEqual(len(selected), 25)
        self.assertEqual(accounting.baseline_backfill, 5)
        self.assertEqual(selected[-1].candidate.user_id, 25)

    def test_all_allocations_are_deterministic_and_capped(self) -> None:
        baseline = self._candidates(range(1, 40))
        target_mod = self._candidates(range(20, 60))
        for _, baseline_slots, target_mod_slots in ALLOCATIONS:
            first, _ = allocate_candidates(baseline, target_mod, baseline_slots, target_mod_slots)
            second, _ = allocate_candidates(baseline, target_mod, baseline_slots, target_mod_slots)
            self.assertEqual(first, second)
            self.assertLessEqual(len(first), 25)

    def test_25_0_matches_existing_baseline_priority(self) -> None:
        seeds = (TargetMapSeed(1, 10), TargetMapSeed(2, 20))
        candidates = tuple(
            TargetMapCandidate(value, str(value), (10, 20) if value < 8 else (10,))
            for value in range(1, 35)
        )
        pool = TargetMapCandidatePool(99, "target", seeds, candidates, (), 2)
        priority = source_priority(pool)
        allocated, _ = allocate_candidates(priority, (), 25, 0)
        self.assertEqual(
            [item.candidate.user_id for item in allocated],
            [item.user_id for item in priority[:25]],
        )

    async def test_shared_hydration_cache_avoids_repeat_requests(self) -> None:
        client = AsyncMock()
        client.get_top_plays_by_user_id.return_value = []
        cache = HydrationCacheClient(client)
        for _ in range(4):
            await cache.get_top_plays_by_user_id(42, 100)
        self.assertEqual(cache.actual_top_play_requests, 1)
        client.get_top_plays_by_user_id.assert_awaited_once_with(42, 100)

    @staticmethod
    def _candidates(values: Iterable[int]) -> tuple[TargetMapCandidate, ...]:
        return tuple(TargetMapCandidate(value, str(value), (10, 20)) for value in values)


if __name__ == "__main__":
    unittest.main()

"""Focused tests for T0050 candidate acquisition."""

import unittest
from unittest.mock import AsyncMock

from backend.app.candidates.target_maps import TargetMapCandidate, TargetMapCandidatePool, TargetMapSeed
from backend.app.osu.client import OsuApiClient, OsuLeaderboardUser, OsuRankingPage, OsuRankingUser
from backend.app.recommendation.candidate_acquisition_experiment import (
    HydrationCacheClient,
    acquire_mod_filtered_pool,
    acquire_performance_pool,
    build_mixed_pool,
    performance_neighborhood_pages,
)


class CandidateAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    def test_mod_request_representation_preserves_exact_acronyms(self) -> None:
        for mods, expected in (
            (("HD", "HR"), ["HD", "HR"]),
            (("HD", "DT"), ["HD", "DT"]),
            (("HD", "HR", "DT"), ["HD", "HR", "DT"]),
            ((), ["NM"]),
        ):
            params = OsuApiClient._beatmap_score_params(mods)
            self.assertEqual([value for key, value in params if key == "mods[]"], expected)

    async def test_mod_pool_deduplicates_and_counts_recurrence(self) -> None:
        client = AsyncMock()
        client.get_beatmap_leaderboard_users.side_effect = [
            (OsuLeaderboardUser(2, "two"), OsuLeaderboardUser(3, "three")),
            (OsuLeaderboardUser(2, "two"), OsuLeaderboardUser(4, "four")),
        ]
        pool, diagnostics = await acquire_mod_filtered_pool(
            1, "target", (TargetMapSeed(1, 10), TargetMapSeed(2, 20)),
            ("HD", "HR"), client,
        )
        self.assertEqual([item.user_id for item in pool.candidates], [2, 3, 4])
        self.assertEqual(pool.candidates[0].seed_hit_count, 2)
        self.assertEqual([item.unique_users for item in diagnostics], [2, 2])

    def test_rank_maps_to_bounded_neighborhood(self) -> None:
        self.assertEqual(performance_neighborhood_pages(1), (1, 2))
        self.assertEqual(performance_neighborhood_pages(126), (2, 3, 4))
        self.assertEqual(performance_neighborhood_pages(87255), (199, 200))

    async def test_performance_neighborhood_excludes_target_and_is_deterministic(self) -> None:
        client = AsyncMock()
        client.get_osu_performance_ranking.side_effect = [
            OsuRankingPage((OsuRankingUser(1, "target", 126, 1.0), OsuRankingUser(3, "far", 100, 2.0)), None),
            OsuRankingPage((OsuRankingUser(2, "near", 125, 3.0),), None),
            OsuRankingPage((), None),
        ]
        pool, users, pages = await acquire_performance_pool(
            1, "target", 126, (TargetMapSeed(1, 10), TargetMapSeed(2, 20)), client,
        )
        self.assertEqual(pages, (2, 3, 4))
        self.assertEqual([item.user_id for item in users], [2, 3])
        self.assertEqual([item.user_id for item in pool.candidates], [2, 3])

    def test_mixed_tiers_are_exact(self) -> None:
        seeds = (TargetMapSeed(1, 10), TargetMapSeed(2, 20))
        mod = self._pool((self._candidate(1, (10, 20)), self._candidate(2, (10, 20)), self._candidate(3, (10,))), seeds)
        perf = self._pool((self._candidate(3, (10, 20)), self._candidate(4, (10, 20))), seeds)
        pool, sources = build_mixed_pool(99, "target", seeds, mod, perf)
        self.assertEqual([item.user_id for item in pool.candidates], [3, 1, 2, 4])
        self.assertEqual([sources[item.user_id] for item in pool.candidates], ["both", "target_mod", "target_mod", "performance"])

    async def test_hydration_cache_reuses_same_user(self) -> None:
        client = AsyncMock()
        client.get_top_plays_by_user_id.return_value = []
        cache = HydrationCacheClient(client)
        await cache.get_top_plays_by_user_id(10, 100)
        await cache.get_top_plays_by_user_id(10, 100)
        self.assertEqual(cache.actual_top_play_requests, 1)
        client.get_top_plays_by_user_id.assert_awaited_once()

    @staticmethod
    def _candidate(user_id: int, seeds: tuple[int, ...]) -> TargetMapCandidate:
        return TargetMapCandidate(user_id, str(user_id), seeds)

    @staticmethod
    def _pool(candidates: tuple[TargetMapCandidate, ...], seeds: tuple[TargetMapSeed, ...]) -> TargetMapCandidatePool:
        return TargetMapCandidatePool(99, "target", seeds, candidates, (), 0)


if __name__ == "__main__":
    unittest.main()

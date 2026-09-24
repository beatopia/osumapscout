"""Tests for discovery-only placement diagnostics."""

import unittest
from unittest.mock import AsyncMock

from backend.app.recommendation.discovery_only_placement import (
    DiscoveryOnlyCandidate,
    _describe,
    _positive,
    _rank_bucket,
    analyze_discovery_only_placement,
    evaluate_discovery_only_placement,
    first_distinguishing_key,
    neighbors,
)
from backend.app.recommendation.discovery_ranking_separation import analyze_discovery_ranking_separation
from backend.app.recommendation.selection_expansion_analysis import analyze_selection_expansion
from backend.tests.test_selection_expansion_analysis import _recovery


class PlacementWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_t0035_pass_serves_analysis(self) -> None:
        separation = analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
        function = AsyncMock(return_value=separation)
        result = await evaluate_discovery_only_placement("target", separation_function=function)
        function.assert_awaited_once()
        self.assertEqual((result.leaderboard_requests, result.top_play_requests, result.total_data_requests), (5, 25, 30))


class PlacementAnalysisTests(unittest.TestCase):
    def test_identifies_only_maps_absent_from_top10(self) -> None:
        result = analyze_discovery_only_placement(
            analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
        )
        self.assertEqual({item.beatmap_id for item in result.candidates}, {104, 105})

    def test_rank_bucket_boundaries(self) -> None:
        ranks = (30, 31, 50, 51, 100, 101, 200, 201, 300, 301)
        self.assertEqual(tuple(_rank_bucket(rank) for rank in ranks), (
            "1-30", "31-50", "31-50", "51-100", "51-100",
            "101-200", "101-200", "201-300", "201-300", "301+",
        ))

    def test_descriptive_summary_has_known_means_and_medians(self) -> None:
        summary = _describe((_candidate(1, 10, 1, 2, 0), _candidate(2, 20, 3, 6, 2)))
        self.assertEqual(summary.mean_support, 2)
        self.assertEqual(summary.median_independent, 4)
        self.assertEqual(summary.mean_iqr_count, 1)
        self.assertEqual(summary.median_rank, 15)

    def test_neighbors_are_deterministic_and_handle_boundaries(self) -> None:
        values = tuple(_candidate(value, value) for value in range(1, 13))
        above, below = neighbors(values, 10)
        self.assertEqual([x.rank for x in above], [5, 6, 7, 8, 9])
        self.assertEqual([x.rank for x in below], [11, 12])
        self.assertEqual(neighbors(values, 1)[0], ())

    def test_every_ranking_key_can_be_first_difference(self) -> None:
        base = _candidate(10, 10, 2, 5, 2, 11)
        cases = (
            (_candidate(1, 1, 3, 5, 2, 11), "support_count"),
            (_candidate(1, 1, 2, 5, 3, 11), "attributes_within_iqr_count"),
            (_candidate(1, 1, 2, 6, 2, 11), "total_independent_shared_count"),
            (_candidate(1, 1, 2, 5, 2, 12), "best_supporting_player_rank"),
            (_candidate(1, 1, 2, 5, 2, 11), "beatmap_id"),
        )
        for above, expected in cases:
            self.assertEqual(first_distinguishing_key(above, base), expected)

    def test_same_support_and_missing_metadata_remain_explicit(self) -> None:
        first = _candidate(1, 1, support=1)
        second = _candidate(2, 2, support=1)
        positive = _positive(0, second, 50, (first, second))
        self.assertEqual(positive.highest_same_support, first)
        candidate = _candidate(1, 1, star=None, ar=None, bpm=None)
        self.assertIsNone(candidate.star_delta)
        self.assertIsNone(candidate.star_within_iqr)


def _candidate(beatmap_id: int, rank: int, support: int = 1, independent: int = 1,
               iqr: int = 1, best: int = 11, star: float | None = 0.1,
               ar: float | None = 0.2, bpm: float | None = 1.0) -> DiscoveryOnlyCandidate:
    return DiscoveryOnlyCandidate(
        beatmap_id, rank, support, independent, independent / support, best,
        (best,), iqr, None if star is None else True, None if ar is None else True,
        None if bpm is None else True, star, ar, bpm,
    )


if __name__ == "__main__":
    unittest.main()

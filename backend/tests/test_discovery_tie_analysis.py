"""Tests for discovery-only tie-group diagnostics."""

import unittest
from unittest.mock import AsyncMock

from backend.app.recommendation.discovery_only_placement import DiscoveryOnlyCandidate
from backend.app.recommendation.discovery_tie_analysis import (
    _positive, _stage, _stage4_group, dominates, evaluate_discovery_ties,
)
from backend.app.recommendation.discovery_only_placement import analyze_discovery_only_placement
from backend.app.recommendation.discovery_ranking_separation import analyze_discovery_ranking_separation
from backend.app.recommendation.selection_expansion_analysis import analyze_selection_expansion
from backend.tests.test_selection_expansion_analysis import _recovery


class TieWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_one_placement_pass(self) -> None:
        placement = analyze_discovery_only_placement(
            analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
        )
        function = AsyncMock(return_value=placement)
        result = await evaluate_discovery_ties("target", placement_function=function)
        function.assert_awaited_once()
        self.assertEqual((result.leaderboard_requests, result.top_play_requests, result.total_data_requests), (5, 25, 30))


class TieAnalysisTests(unittest.TestCase):
    def test_tie_stages_and_group_sizes(self) -> None:
        values = (
            _candidate(1, 1, 1, 0, 1, 11), _candidate(2, 2, 1, 1, 2, 12),
            _candidate(3, 3, 2, 1, 3, 11), _candidate(4, 4, 2, 1, 4, 12),
            _candidate(5, 5, 3, 2, 5, 11), _candidate(6, 6, 3, 2, 5, 12),
            _candidate(7, 7, 4, 3, 6, 13), _candidate(8, 8, 4, 3, 6, 13),
        )
        fields = ("support_count", "attributes_within_iqr_count", "total_independent_shared_count", "best_supporting_player_rank")
        summaries = [_stage(index, values, fields[:index]) for index in range(1, 5)]
        self.assertEqual([item.candidates_in_groups for item in summaries], [8, 6, 4, 2])
        self.assertEqual(summaries[-1].maximum_group_size, 2)

    def test_stage4_variation_and_missing_are_explicit(self) -> None:
        group = _stage4_group((
            _candidate(1, 100, star=.1, ar=.1, bpm=5),
            _candidate(2, 120, star=.2, ar=.1, bpm=8),
        ))
        self.assertTrue(group.star_varies)
        self.assertFalse(group.ar_varies)
        self.assertTrue(group.bpm_varies)
        missing = _stage4_group((_candidate(1, 1, star=None), _candidate(2, 2, star=.2)))
        self.assertFalse(missing.star_complete)

    def test_dominance_and_tradeoff(self) -> None:
        better = _candidate(1, 1, star=.1, ar=.1, bpm=5)
        worse = _candidate(2, 2, star=.2, ar=.1, bpm=8)
        tradeoff = _candidate(3, 3, star=.05, ar=.2, bpm=4)
        self.assertTrue(dominates(better, worse))
        self.assertFalse(dominates(better, tradeoff))

    def test_positive_bounds_and_beatmap_position(self) -> None:
        group = tuple(_candidate(identifier, rank) for identifier, rank in ((1, 100), (2, 116), (3, 120)))
        result = _positive(group[1], group)
        self.assertEqual((result.minimum_rank, result.candidate_rank, result.maximum_rank), (100, 116, 120))
        self.assertEqual(result.unresolved_rank_uncertainty, 20)
        self.assertEqual(result.beatmap_id_position, 2)


def _candidate(beatmap_id: int, rank: int, support: int = 1, iqr: int = 1,
               independent: int = 1, best: int = 11, star: float | None = .1,
               ar: float | None = .1, bpm: float | None = 5) -> DiscoveryOnlyCandidate:
    return DiscoveryOnlyCandidate(
        beatmap_id, rank, support, independent, independent / support, best, (best,), iqr,
        None if star is None else True, None if ar is None else True, None if bpm is None else True,
        star, ar, bpm,
    )


if __name__ == "__main__":
    unittest.main()

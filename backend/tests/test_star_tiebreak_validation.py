"""Tests for expanded star-only tie-break validation."""

import unittest
from unittest.mock import AsyncMock

from backend.app.recommendation.discovery_ranking_separation import analyze_discovery_ranking_separation
from backend.app.recommendation.selection_expansion_analysis import analyze_selection_expansion
from backend.app.recommendation.star_tiebreak_validation import (
    NEW_SPLITS, aggregate_star_results, analyze_star_validation,
    evaluate_star_validation, split_position_coverage, summarize_properties,
)
from backend.app.recommendation.continuous_tiebreak_experiment import (
    PositiveMovement, summarize_direction, summarize_transitions,
)
from backend.tests.test_selection_expansion_analysis import _recovery


EXPECTED_SPLITS = (
    (1, 12, 23, 34, 45, 56, 67, 78, 89, 100),
    (1, 2, 13, 24, 35, 46, 57, 68, 79, 90),
    (2, 3, 14, 25, 36, 47, 58, 69, 80, 91),
    (3, 4, 15, 26, 37, 48, 59, 70, 81, 92),
    (4, 5, 16, 27, 38, 49, 60, 71, 82, 93),
    (5, 6, 17, 28, 39, 50, 61, 72, 83, 94),
    (6, 7, 18, 29, 40, 51, 62, 73, 84, 95),
    (7, 8, 19, 30, 41, 52, 63, 74, 85, 96),
)


class StarWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_pass_and_split_count_eight(self) -> None:
        separation = analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
        function = AsyncMock(return_value=separation)
        result = await evaluate_star_validation("target", split_index=7, separation_function=function)
        self.assertEqual(function.await_args.kwargs["split_count"], 8)
        self.assertEqual(result.total_data_requests, 30)


class StarValidationTests(unittest.TestCase):
    def test_historical_and_new_split_positions(self) -> None:
        positions, covered = split_position_coverage()
        self.assertEqual(positions, EXPECTED_SPLITS)
        self.assertEqual(positions[:5], EXPECTED_SPLITS[:5])
        self.assertEqual(NEW_SPLITS, (3, 4, 5, 6, 7))
        self.assertEqual(covered, 73)

    def test_candidate_and_outside_group_invariants(self) -> None:
        result = _result("target", 3)
        self.assertTrue(result.candidate_sets_equal)
        self.assertTrue(result.outside_group_stable)

    def test_positive_details_have_fit_position_and_peer_counts(self) -> None:
        positive = _positive(change=-4, beatmap=1)
        self.assertEqual(positive.star_group_position, 2)
        self.assertEqual((positive.peers_with_smaller_star_delta, positive.peers_with_larger_star_delta), (1, 3))

    def test_property_summaries_and_duplicate_accounting(self) -> None:
        improved = _positive(change=-4, beatmap=1)
        worsened = _positive(change=3, beatmap=2)
        summary = summarize_properties((improved, worsened))
        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.mean_support, 1)
        first = _result("target", 3, (improved,))
        repeated = _result("target", 4, (improved, worsened))
        aggregate = aggregate_star_results((first, repeated))
        self.assertEqual(aggregate.positive_count, 3)
        self.assertEqual(aggregate.unique_positive_count, 2)
        self.assertEqual((aggregate.direction.improved, aggregate.direction.worsened), (2, 1))

    def test_cutoff_transition_uses_split_observations(self) -> None:
        entering = _positive(change=-10, beatmap=3, baseline=105)
        aggregate = aggregate_star_results((_result("target", 3, (entering,)),))
        top100 = next(item for item in aggregate.transitions if item.cutoff == 100)
        self.assertEqual(top100.entered, 1)


def _result(target: str, split: int, positives=()):
    separation = analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
    result = analyze_star_validation(target, separation)
    return result.__class__(target, split, result.baseline, result.star, result.candidate_sets_equal,
        result.outside_group_stable, result.movement, result.remaining_ties, tuple(positives),
        summarize_direction([p.signed_change('star') for p in positives]),
        summarize_transitions(positives, "star"), result.leaderboard_requests, result.top_play_requests)


def _positive(change: int, beatmap: int, baseline: int = 50) -> PositiveMovement:
    return PositiveMovement(
        20, beatmap, baseline, baseline + change, baseline, baseline,
        5, baseline - 2, baseline + 2, .2, .1, 5.0,
        1, 2, 4, 13, 3, 2, 80.0, 1, 3,
    )


if __name__ == "__main__":
    unittest.main()

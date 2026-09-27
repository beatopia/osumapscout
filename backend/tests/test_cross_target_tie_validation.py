"""Tests for pure cross-target tie aggregation."""

import unittest
from dataclasses import replace

from backend.app.recommendation.cross_target_tie_validation import (
    TARGETS, TargetSplitTieSummary, aggregate_cross_target_ties,
    aggregate_target_ties, compact_summary,
)
from backend.app.recommendation.discovery_only_placement import analyze_discovery_only_placement
from backend.app.recommendation.discovery_ranking_separation import analyze_discovery_ranking_separation
from backend.app.recommendation.discovery_tie_analysis import (
    EvidenceCompleteness, Stage4Group, analyze_discovery_ties,
)
from backend.app.recommendation.selection_expansion_analysis import analyze_selection_expansion
from backend.tests.test_selection_expansion_analysis import _recovery


class CrossTargetAggregationTests(unittest.TestCase):
    def test_equal_targets_have_equal_weighted_and_unweighted_rates(self) -> None:
        aggregate = aggregate_cross_target_ties((
            TargetSplitTieSummary("A", _result(0, 100, 90)),
            TargetSplitTieSummary("B", _result(0, 100, 50)),
        ))
        self.assertEqual(aggregate.weighted_stage4_rate, .7)
        self.assertEqual(aggregate.unweighted_mean_target_rate, .7)

    def test_unequal_counts_distinguish_weighted_and_unweighted(self) -> None:
        aggregate = aggregate_cross_target_ties((
            TargetSplitTieSummary("A", _result(0, 100, 90)),
            TargetSplitTieSummary("B", _result(0, 20, 10)),
        ))
        self.assertAlmostEqual(aggregate.weighted_stage4_rate, 100 / 120)
        self.assertEqual(aggregate.unweighted_mean_target_rate, .7)

    def test_per_target_aggregation_and_partial_splits_are_explicit(self) -> None:
        summaries = (
            TargetSplitTieSummary("A", _result(0, 100, 90)),
            TargetSplitTieSummary("A", _result(2, 50, 40)),
            TargetSplitTieSummary("B", _result(0, 20, 10)),
        )
        target = aggregate_target_ties("A", summaries)
        self.assertEqual(target.completed_splits, (0, 2))
        self.assertEqual((target.candidate_count, target.stage4_count), (150, 130))

    def test_continuous_numerators_use_group_denominator(self) -> None:
        aggregate = aggregate_cross_target_ties((TargetSplitTieSummary("A", _result(0, 10, 8)),))
        self.assertEqual(aggregate.star_variation_rate, 1.0)
        self.assertEqual(aggregate.ar_variation_rate, 0.0)
        self.assertEqual(aggregate.all_complete_group_rate, 1.0)

    def test_target_order_and_machine_summary_are_deterministic(self) -> None:
        self.assertEqual(TARGETS, ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat"))
        line = compact_summary("A", _result(2, 10, 8))
        self.assertTrue(line.startswith("TARGET_TIE_SUMMARY target=A split=2"))
        self.assertIn("total=30", line)

    def test_existing_t0037_analysis_is_not_changed(self) -> None:
        placement = analyze_discovery_only_placement(
            analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
        )
        result = analyze_discovery_ties(placement)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.total_data_requests, 30)


def _result(split: int, candidates: int, tied: int):
    placement = analyze_discovery_only_placement(
        analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
    )
    base = analyze_discovery_ties(placement)
    group = Stage4Group(1, 1, 1, 11, tied, 1, tied, tied, True, True, True,
                        2, 1, 2, True, False, True, True, max(0, tied - 1))
    return replace(
        base, split_index=split, candidate_count=candidates,
        stage4_groups=(group,), largest_stage4_groups=(group,),
        beatmap_id_dependent_count=tied,
        beatmap_id_dependent_rate=tied / candidates,
        star_varying_groups=1, ar_varying_groups=0, bpm_varying_groups=1,
        any_varying_groups=1,
        completeness=EvidenceCompleteness(candidates, candidates, candidates, candidates, candidates),
    )


if __name__ == "__main__":
    unittest.main()

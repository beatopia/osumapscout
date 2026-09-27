"""Tests for descriptive discovery-only provenance analysis."""

import unittest
from unittest.mock import AsyncMock

from backend.app.recommendation.candidate_map_ranking import CandidateMapEvidence
from backend.app.recommendation.candidate_maps import CandidateMap, CandidateMapSupport
from backend.app.recommendation.discovery_provenance_analysis import (
    analyze_discovery_provenance,
    classify_provenance,
    classify_support,
    describe_candidate,
    evaluate_discovery_provenance,
    summarize_population,
)
from backend.app.recommendation.discovery_ranking_separation import (
    analyze_discovery_ranking_separation,
)
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    NumericCandidateEvidence,
)
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate
from backend.app.recommendation.selection_expansion_analysis import (
    analyze_selection_expansion,
)
from backend.tests.test_selection_expansion_analysis import _recovery


class ProvenanceWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_one_pass_without_changing_ranks(self) -> None:
        separation = analyze_discovery_ranking_separation(
            analyze_selection_expansion(_recovery())
        )
        function = AsyncMock(return_value=separation)
        result = await evaluate_discovery_provenance(
            "target", split_index=8, separation_function=function
        )
        self.assertEqual(function.await_args.kwargs["split_count"], 13)
        self.assertEqual(result.total_data_requests, 30)
        self.assertTrue(result.ranks_unchanged)


class ProvenanceTests(unittest.TestCase):
    def test_support_and_provenance_classification(self) -> None:
        self.assertEqual(classify_support(1), "single_support")
        self.assertEqual(classify_support(2), "multi_support")
        self.assertEqual(classify_provenance(("recurring",)), "recurring_only")
        self.assertEqual(classify_provenance(("one_hit",)), "one_hit_only")
        self.assertEqual(
            classify_provenance(("recurring", "one_hit")), "mixed_provenance"
        )
        self.assertEqual(classify_provenance((None,)), "unknown")

    def test_alignment_true_false_and_ranges(self) -> None:
        aligned = describe_candidate(
            _candidate(1, 20, ((13, 5, "recurring"), (14, 20, "one_hit")))
        )
        self.assertEqual(aligned.best_position_supporter_rank, 13)
        self.assertTrue(aligned.best_position_supporter_is_best_similarity_supporter)
        self.assertEqual(aligned.top_play_position_range, 15)
        self.assertEqual(aligned.similarity_rank_range, 1)
        self.assertEqual(aligned.acquisition_classification, "mixed_provenance")

        not_aligned = describe_candidate(
            _candidate(2, 21, ((13, 20, "recurring"), (14, 5, "recurring")))
        )
        self.assertEqual(not_aligned.best_position_supporter_rank, 14)
        self.assertFalse(
            not_aligned.best_position_supporter_is_best_similarity_supporter
        )

    def test_known_positive_other_aggregation(self) -> None:
        single = describe_candidate(
            _candidate(1, 10, ((13, 8, "recurring"),)),
            target_position=20,
        )
        multi = describe_candidate(
            _candidate(2, 30, ((14, 10, "one_hit"), (15, 40, "one_hit")))
        )
        summary = summarize_population((single, multi))
        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.single_support.rate, 0.5)
        self.assertEqual(summary.multi_support.rate, 0.5)
        self.assertEqual(summary.recurring_only.rate, 0.5)
        self.assertEqual(summary.one_hit_only.rate, 0.5)
        self.assertEqual(summary.best_supporter_rank.mean, 13.5)
        self.assertEqual(summary.support_count.median, 1.5)
        self.assertEqual(summary.best_supporter_position.mean, 9)

    def test_diagnostic_preserves_existing_baseline(self) -> None:
        separation = analyze_discovery_ranking_separation(
            analyze_selection_expansion(_recovery())
        )
        result = analyze_discovery_provenance("target", separation)
        self.assertTrue(result.ranks_unchanged)
        native_ids = {
            item.preference_evidence.collaborative.candidate_map.beatmap_id
            for item in separation.top10.preference
        }
        expected = [
            item.preference_rank
            for item in separation.hybrid.preference
            if item.preference_evidence.collaborative.candidate_map.beatmap_id
            not in native_ids
        ]
        self.assertEqual(
            [item.baseline_rank for item in result.candidates], expected
        )


def _candidate(
    beatmap_id: int,
    rank: int,
    supports: tuple[tuple[int, int, str], ...],
) -> PreferenceRankedCandidate:
    map_supports = tuple(
        CandidateMapSupport(
            user_id=index,
            username=None,
            similar_player_rank=similar_rank,
            independent_shared_count=2,
            seed_excluded_jaccard_similarity=0.1,
            seed_excluded_target_coverage=0.1,
            mods=(),
            performance_points=None,
            supporter_top_play_position=position,
            acquisition_group=group,
            seed_hit_count=2 if group == "recurring" else 1,
        )
        for index, (similar_rank, position, group) in enumerate(supports, start=1)
    )
    candidate_map = CandidateMap(
        beatmap_id, None, None, None, None, None, None, map_supports
    )
    collaborative = CandidateMapEvidence(
        candidate_map,
        len(map_supports),
        sum(item.independent_shared_count for item in map_supports),
        2.0,
        min(item.similar_player_rank for item in map_supports),
        sum(item.similar_player_rank for item in map_supports) / len(map_supports),
        rank,
        rank,
    )
    numeric = NumericCandidateEvidence(None, None, None)
    evidence = CandidatePreferenceEvidence(
        collaborative, numeric, numeric, numeric, 0, 0, (), (), None
    )
    return PreferenceRankedCandidate(evidence, rank)


if __name__ == "__main__":
    unittest.main()

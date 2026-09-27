"""Tests for isolated single-field continuous tie-break views."""

import unittest
from dataclasses import replace
from unittest.mock import AsyncMock

from backend.app.recommendation.continuous_tiebreak_experiment import (
    PositiveMovement, _groups, _remaining, _rerank, analyze_continuous_tiebreak,
    evaluate_continuous_tiebreak, summarize_direction, summarize_transitions,
)
from backend.app.recommendation.discovery_ranking_separation import analyze_discovery_ranking_separation
from backend.app.recommendation.selection_expansion_analysis import analyze_selection_expansion
from backend.tests.test_selection_expansion_analysis import _preference, _recovery


class ContinuousWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_evidence_pass_serves_all_views(self) -> None:
        separation = analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
        function = AsyncMock(return_value=separation)
        result = await evaluate_continuous_tiebreak("target", separation_function=function)
        function.assert_awaited_once()
        self.assertEqual(result.total_data_requests, 30)
        self.assertTrue(result.candidate_sets_equal)
        recovered = {getattr(result, name).recovery.recovered_anywhere for name in ("baseline", "star", "ar", "bpm")}
        self.assertEqual(len(recovered), 1)


class ContinuousRankingTests(unittest.TestCase):
    def test_fields_only_break_exact_discrete_ties(self) -> None:
        high_support = _candidate(1, 1, support=2, star=.9, ar=.9, bpm=90)
        first = _candidate(20, 2, star=.3, ar=.1, bpm=30)
        second = _candidate(10, 3, star=.1, ar=.3, bpm=10)
        baseline = (high_support, first, second)
        groups = _groups(baseline)
        self.assertEqual(_ids(_rerank(baseline, groups, "star")), [1, 10, 20])
        self.assertEqual(_ids(_rerank(baseline, groups, "ar")), [1, 20, 10])
        self.assertEqual(_ids(_rerank(baseline, groups, "bpm")), [1, 10, 20])

    def test_beatmap_id_fallback_and_missing_values(self) -> None:
        present = _candidate(30, 1, star=.2)
        missing_low = _candidate(10, 2, star=None)
        missing_high = _candidate(20, 3, star=None)
        tied_present = _candidate(5, 4, star=.2)
        baseline = (present, missing_low, missing_high, tied_present)
        ranked = _rerank(baseline, _groups(baseline), "star")
        self.assertEqual(_ids(ranked), [5, 30, 10, 20])

    def test_remaining_ties_count_only_equal_continuous_values(self) -> None:
        values = (_candidate(1, 1, star=.1), _candidate(2, 2, star=.1), _candidate(3, 3, star=.2))
        summary = _remaining(_groups(values), "star", 3)
        self.assertEqual((summary.groups, summary.candidates), (1, 2))

    def test_signed_movement_and_cutoff_crossings(self) -> None:
        positive = PositiveMovement(
            1, 1, 105, 95, 110, 105, 3, 100, 110, .1, .1, 1,
            1, 2, 3, 11, 3, 1, 100.0, 0, 2,
        )
        direction = summarize_direction((positive.signed_change("star"), positive.signed_change("ar")))
        self.assertEqual((direction.improved, direction.worsened), (1, 1))
        star = {item.cutoff: item for item in summarize_transitions((positive,), "star")}
        ar = {item.cutoff: item for item in summarize_transitions((positive,), "ar")}
        self.assertEqual(star[100].entered, 1)
        self.assertEqual(ar[100].exited, 0)

    def test_existing_hybrid_baseline_is_unchanged(self) -> None:
        separation = analyze_discovery_ranking_separation(analyze_selection_expansion(_recovery()))
        result = analyze_continuous_tiebreak("target", separation)
        self.assertEqual(_ids(result.baseline.candidates), _ids(separation.hybrid.preference))
        self.assertTrue(result.outside_group_stable)


def _candidate(beatmap_id: int, rank: int, *, support: int = 1,
               star: float | None = .1, ar: float | None = .1,
               bpm: float | None = 10):
    item = _preference(beatmap_id, rank)
    evidence = item.preference_evidence
    collab = replace(evidence.collaborative, support_count=support,
                     total_independent_shared_count=1,
                     best_supporting_player_rank=11)
    def numeric(original, value):
        return replace(original, delta_from_target_median=value,
                       within_target_iqr=None if value is None else True)
    evidence = replace(evidence, collaborative=collab,
        star_rating=numeric(evidence.star_rating, star),
        approach_rate=numeric(evidence.approach_rate, ar),
        bpm=numeric(evidence.bpm, bpm), attributes_within_iqr_count=1)
    return replace(item, preference_evidence=evidence, preference_rank=rank)


def _ids(items):
    return [item.preference_evidence.collaborative.candidate_map.beatmap_id for item in items]


if __name__ == "__main__":
    unittest.main()

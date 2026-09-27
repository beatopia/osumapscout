"""Tests for the isolated supporter top-play-position experiment."""

import unittest
from unittest.mock import AsyncMock

from backend.app.recommendation.candidate_map_ranking import CandidateMapEvidence
from backend.app.recommendation.candidate_maps import CandidateMap, CandidateMapSupport
from backend.app.recommendation.continuous_tiebreak_experiment import _groups
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
from backend.app.recommendation.supporter_play_rank_experiment import (
    NEW_SPLITS,
    SupporterPositionPositive,
    analyze_supporter_play_rank,
    evaluate_supporter_play_rank,
    rerank_by_supporter_position,
    split_position_coverage,
    summarize_position_transitions,
    supporter_position_evidence,
)
from backend.tests.test_selection_expansion_analysis import _recovery


EXPECTED_HISTORICAL = (
    (1, 12, 23, 34, 45, 56, 67, 78, 89, 100),
    (1, 2, 13, 24, 35, 46, 57, 68, 79, 90),
    (2, 3, 14, 25, 36, 47, 58, 69, 80, 91),
    (3, 4, 15, 26, 37, 48, 59, 70, 81, 92),
    (4, 5, 16, 27, 38, 49, 60, 71, 82, 93),
    (5, 6, 17, 28, 39, 50, 61, 72, 83, 94),
    (6, 7, 18, 29, 40, 51, 62, 73, 84, 95),
    (7, 8, 19, 30, 41, 52, 63, 74, 85, 96),
)


class SupporterPositionWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_pass_uses_thirteen_splits_and_thirty_requests(self) -> None:
        separation = analyze_discovery_ranking_separation(
            analyze_selection_expansion(_recovery())
        )
        function = AsyncMock(return_value=separation)
        result = await evaluate_supporter_play_rank(
            "target", split_index=12, separation_function=function
        )
        self.assertEqual(function.await_args.kwargs["split_count"], 13)
        self.assertEqual(result.total_data_requests, 30)
        self.assertTrue(result.candidate_sets_equal)
        self.assertTrue(result.recovery_equal)
        self.assertTrue(result.outside_group_stable)


class SupporterPositionTests(unittest.TestCase):
    def test_multi_supporter_position_aggregation(self) -> None:
        candidate = _candidate(1, 1, positions=(8, 42))
        evidence = supporter_position_evidence(candidate)
        self.assertEqual(evidence.positions, (8, 42))
        self.assertEqual(evidence.best, 8)
        self.assertEqual(evidence.mean, 25)

    def test_tie_break_and_beatmap_fallback(self) -> None:
        baseline = (
            _candidate(20, 1, positions=(40,)),
            _candidate(10, 2, positions=(5,)),
            _candidate(30, 3, positions=(5,)),
        )
        ranked = rerank_by_supporter_position(baseline, _groups(baseline))
        self.assertEqual([_beatmap(item) for item in ranked], [10, 30, 20])

    def test_present_sorts_before_missing(self) -> None:
        baseline = (
            _candidate(30, 1, positions=()),
            _candidate(20, 2, positions=()),
            _candidate(10, 3, positions=(50,)),
        )
        ranked = rerank_by_supporter_position(baseline, _groups(baseline))
        self.assertEqual([_beatmap(item) for item in ranked], [10, 20, 30])

    def test_earlier_key_prevents_reordering(self) -> None:
        baseline = (
            _candidate(20, 1, positions=(90,), iqr=2),
            _candidate(10, 2, positions=(1,), iqr=1),
        )
        ranked = rerank_by_supporter_position(baseline, _groups(baseline))
        self.assertEqual([_beatmap(item) for item in ranked], [20, 10])

    def test_entering_and_leaving_top100(self) -> None:
        entering = _positive(101, 99)
        leaving = _positive(99, 101)
        top100 = next(
            item
            for item in summarize_position_transitions((entering, leaving))
            if item.cutoff == 100
        )
        self.assertEqual((top100.entered, top100.exited), (1, 1))

    def test_historical_stability_and_new_determinism(self) -> None:
        positions, covered = split_position_coverage()
        self.assertEqual(positions[:8], EXPECTED_HISTORICAL)
        self.assertEqual(NEW_SPLITS, (8, 9, 10, 11, 12))
        self.assertEqual(positions[8], (8, 9, 20, 31, 42, 53, 64, 75, 86, 97))
        self.assertEqual(positions[12], (1, 12, 13, 24, 35, 46, 57, 68, 79, 90))
        self.assertEqual(covered, 100)

    def test_t0040_analysis_remains_compatible(self) -> None:
        separation = analyze_discovery_ranking_separation(
            analyze_selection_expansion(_recovery())
        )
        result = analyze_supporter_play_rank("target", separation)
        self.assertEqual(result.baseline.candidates, separation.hybrid.preference)


def _candidate(
    beatmap_id: int,
    rank: int,
    *,
    positions: tuple[int, ...],
    iqr: int = 1,
) -> PreferenceRankedCandidate:
    supports = tuple(
        CandidateMapSupport(
            user_id=index,
            username=f"player-{index}",
            similar_player_rank=1,
            independent_shared_count=2,
            seed_excluded_jaccard_similarity=0.1,
            seed_excluded_target_coverage=0.1,
            mods=(),
            performance_points=None,
            supporter_top_play_position=position,
        )
        for index, position in enumerate(positions, start=1)
    )
    if not positions:
        supports = (
            CandidateMapSupport(1, "player", 1, 2, 0.1, 0.1, (), None),
        )
    candidate_map = CandidateMap(
        beatmap_id, None, None, None, 5.0, 8.5, 180.0, supports
    )
    collaborative = CandidateMapEvidence(
        candidate_map, 1, 2, 2.0, 1, 1.0, rank, rank
    )
    numeric = NumericCandidateEvidence(5.0, 0.0, True)
    preference = CandidatePreferenceEvidence(
        collaborative, numeric, numeric, numeric, iqr, 3, (), (), None
    )
    return PreferenceRankedCandidate(preference, rank)


def _beatmap(item: PreferenceRankedCandidate) -> int:
    return item.preference_evidence.collaborative.candidate_map.beatmap_id


def _positive(baseline: int, experimental: int) -> SupporterPositionPositive:
    return SupporterPositionPositive(
        1, 1, baseline, experimental, (5,), 5, 5.0,
        3, 99, 101, 2, 1, 100.0, 0, 2, 0,
    )


if __name__ == "__main__":
    unittest.main()

"""Tests for held-out top-play recovery and anti-leakage rules."""

import unittest

from backend.app.candidates.target_maps import TargetMapSeed, select_evenly_spaced_seeds
from backend.app.recommendation.holdout_recovery import (
    HoldoutRecoveryExperimentResult,
    OrderingRecoverySummary,
    RecoveredRankSummary,
    SplitPositionDiagnostics,
    TargetPlayEvidence,
    aggregate_split_summaries,
    calculate_split_position_sets,
    split_target_evidence,
    summarize_recovery,
)
from backend.app.recommendation.verify_holdout_recovery import format_split_summary
from backend.app.similarity.target_map_overlap import calculate_raw_and_seed_excluded_overlap


class HoldoutSelectionTests(unittest.TestCase):
    def test_selection_is_deterministic_even_and_unique(self) -> None:
        plays = tuple(self._play(position) for position in range(1, 101))

        first = split_target_evidence(plays, 10)
        second = split_target_evidence(plays, 10)

        self.assertEqual(first, second)
        self.assertEqual(
            [play.position for play in first.held_out],
            [1, 12, 23, 34, 45, 56, 67, 78, 89, 100],
        )
        self.assertEqual(len({play.position for play in first.held_out}), 10)
        self.assertEqual(len(first.training), 90)

    def test_single_holdout_uses_middle_and_invalid_counts_fail(self) -> None:
        plays = tuple(self._play(position) for position in range(1, 6))
        split = split_target_evidence(plays, 1)
        self.assertEqual([play.position for play in split.held_out], [3])
        for count in (0, 5, 6, 21):
            with self.assertRaises(ValueError):
                split_target_evidence(plays, count)

    def test_held_out_map_cannot_become_seed(self) -> None:
        plays = tuple(self._play(position) for position in range(1, 6))
        split = split_target_evidence(plays, 1)
        seeds = select_evenly_spaced_seeds(
            tuple(TargetMapSeed(play.position, play.beatmap_id) for play in split.training),
            4,
        )

        self.assertEqual([seed.beatmap_id for seed in seeds], [1, 2, 4, 5])
        self.assertNotIn(3, [seed.beatmap_id for seed in seeds])

    def test_split_zero_regression_and_later_splits_differ(self) -> None:
        diagnostics = calculate_split_position_sets(100, 10, 5)

        self.assertEqual(
            diagnostics.split_positions[0],
            (1, 12, 23, 34, 45, 56, 67, 78, 89, 100),
        )
        self.assertEqual(diagnostics, calculate_split_position_sets(100, 10, 5))
        self.assertEqual(len(diagnostics.split_positions), 5)
        self.assertEqual(len(set(diagnostics.split_positions)), 5)
        self.assertTrue(
            all(len(set(positions)) == 10 for positions in diagnostics.split_positions)
        )
        self.assertTrue(
            all(max(positions) - min(positions) >= 80 for positions in diagnostics.split_positions)
        )

    def test_cross_split_coverage_is_pure_and_correct(self) -> None:
        diagnostics = calculate_split_position_sets(10, 2, 3)
        self.assertEqual(diagnostics.split_positions, ((1, 10), (1, 2), (2, 3)))
        self.assertEqual(diagnostics.unique_positions_covered, 4)
        self.assertEqual(diagnostics.target_count, 10)

    def test_split_bounds_are_enforced(self) -> None:
        plays = tuple(self._play(position) for position in range(1, 11))
        for split_count in (1, 11):
            with self.assertRaises(ValueError):
                split_target_evidence(plays, 2, split_count, 0)
        for split_index in (-1, 5):
            with self.assertRaises(ValueError):
                split_target_evidence(plays, 2, 5, split_index)

    def test_nonzero_split_preserves_anti_leakage_boundary(self) -> None:
        plays = tuple(self._play(position) for position in range(1, 11))
        split = split_target_evidence(plays, 2, 5, 1)
        held_out_ids = {play.beatmap_id for play in split.held_out}
        seeds = select_evenly_spaced_seeds(
            tuple(TargetMapSeed(play.position, play.beatmap_id) for play in split.training),
            5,
        )
        self.assertTrue(held_out_ids.isdisjoint(seed.beatmap_id for seed in seeds))

        held_out_id = next(iter(held_out_ids))
        training_ids = {play.beatmap_id for play in split.training}
        candidate_ids = {held_out_id, next(iter(training_ids)), 99} - training_ids
        self.assertEqual(candidate_ids, {held_out_id, 99})

    @staticmethod
    def _play(position: int) -> TargetPlayEvidence:
        return TargetPlayEvidence(
            position=position,
            beatmap_id=position,
            artist=None,
            title=None,
            difficulty_name=None,
            star_rating=None,
            approach_rate=None,
            bpm=None,
            mods=(),
        )


class AntiLeakageMetricTests(unittest.TestCase):
    def test_held_out_map_does_not_count_toward_similarity(self) -> None:
        metrics = calculate_raw_and_seed_excluded_overlap(
            (1, 2, 3),
            (1, 9),
            (),
        )
        self.assertEqual(metrics.raw.shared_beatmap_count, 1)
        self.assertEqual(metrics.seed_excluded.shared_beatmap_count, 1)

    def test_training_exclusion_leaves_held_out_map_eligible(self) -> None:
        training_ids = {1, 2, 3}
        similar_player_ids = {2, 9, 10}
        candidate_ids = similar_player_ids - training_ids
        self.assertEqual(candidate_ids, {9, 10})
        self.assertNotIn(2, candidate_ids)


class RecoverySummaryTests(unittest.TestCase):
    def test_counts_recovery_and_recall_at_cutoffs(self) -> None:
        ordering = (5, 10, 7, 8, 20) + tuple(range(100, 110))
        summary = summarize_recovery((10, 20, 30), ordering)

        self.assertEqual(summary.recovered_anywhere, 2)
        self.assertAlmostEqual(summary.recovery_rate, 2 / 3)
        self.assertEqual(summary.recovered_at_10, 2)
        self.assertAlmostEqual(summary.recall_at_10, 2 / 3)

    def test_rank_statistics_odd_even_none_and_all(self) -> None:
        odd = summarize_recovery((1, 2, 3), (1, 9, 2, 8, 3))
        even = summarize_recovery((1, 2), (9, 1, 8, 2))
        none = summarize_recovery((1, 2), (3, 4))
        all_recovered = summarize_recovery((1, 2), (2, 1))

        assert odd.recovered_rank_summary is not None
        self.assertEqual(odd.recovered_rank_summary.median, 3.0)
        assert even.recovered_rank_summary is not None
        self.assertEqual(even.recovered_rank_summary.median, 3.0)
        self.assertIsNone(none.recovered_rank_summary)
        self.assertEqual(all_recovered.recovered_anywhere, 2)

    def test_two_orderings_are_evaluated_independently(self) -> None:
        held_out = (10, 20)
        support_only = summarize_recovery(held_out, (10, 5, 20))
        evidence_aware = summarize_recovery(held_out, (5, 20, 10))
        self.assertEqual(support_only.recovered_rank_summary.minimum, 1)  # type: ignore[union-attr]
        self.assertEqual(evidence_aware.recovered_rank_summary.minimum, 2)  # type: ignore[union-attr]

    def test_aggregate_helper_combines_explicit_summaries(self) -> None:
        support_one = summarize_recovery((1, 2), (1, 9))
        evidence_one = summarize_recovery((1, 2), (1, 2))
        support_two = summarize_recovery((3, 4), (8, 3))
        evidence_two = summarize_recovery((3, 4), (8, 3, 4))

        aggregate = aggregate_split_summaries(
            (
                (support_one, evidence_one, support_one),
                (support_two, evidence_two, evidence_two),
            )
        )

        self.assertEqual(aggregate.split_count, 2)
        self.assertEqual(aggregate.support_only.total_held_out, 4)
        self.assertEqual(aggregate.support_only.total_recovered_anywhere, 2)
        self.assertEqual(aggregate.support_only.micro_recovery_rate, 0.5)
        self.assertEqual(aggregate.support_only.mean_recall_at_10, 0.5)
        self.assertEqual(aggregate.evidence_aware.total_recovered_anywhere, 4)
        self.assertEqual(aggregate.evidence_aware.micro_recovery_rate, 1.0)
        self.assertEqual(
            aggregate.evidence_aware.mean_split_median_recovered_rank, 2.0
        )
        self.assertEqual(aggregate.preference_aware.total_recovered_anywhere, 3)

    def test_summary_line_is_deterministic(self) -> None:
        support = _summary(recovered=1, recall=0.5, median_rank=3.0)
        evidence = _summary(recovered=2, recall=1.0, median_rank=2.5)
        preference = _summary(recovered=1, recall=0.5, median_rank=1.0)
        result = HoldoutRecoveryExperimentResult(
            target_user_id=1,
            target_username="target",
            original_target_play_count=4,
            training_play_count=2,
            held_out_play_count=2,
            selected_seeds=(),
            candidates_hydrated=0,
            similar_players_used=0,
            leaderboard_requests_made=0,
            top_play_requests_made=0,
            additional_recovery_requests=0,
            held_out_maps=(),
            support_only_summary=support,
            evidence_aware_summary=evidence,
            preference_aware_summary=preference,
            split_count=5,
            split_index=1,
            split_diagnostics=SplitPositionDiagnostics(((1, 4),), 2, 4),
        )

        self.assertEqual(
            format_split_summary(result),
            "SPLIT_SUMMARY split=1 heldout=2 recovered=1 "
            "support_r10=0.5000 support_r30=0.5000 support_r50=0.5000 "
            "support_r100=0.5000 support_median=3.0 evidence_recovered=2 "
            "evidence_r10=1.0000 evidence_r30=1.0000 evidence_r50=1.0000 "
            "evidence_r100=1.0000 evidence_median=2.5 "
            "preference_recovered=1 preference_r10=0.5000 "
            "preference_r30=0.5000 preference_r50=0.5000 "
            "preference_r100=0.5000 preference_median=1.0",
        )


def _summary(
    recovered: int,
    recall: float,
    median_rank: float,
) -> OrderingRecoverySummary:
    return OrderingRecoverySummary(
        held_out_count=2,
        recovered_anywhere=recovered,
        recovery_rate=recovered / 2,
        recovered_at_10=recovered,
        recovered_at_30=recovered,
        recovered_at_50=recovered,
        recovered_at_100=recovered,
        recall_at_10=recall,
        recall_at_30=recall,
        recall_at_50=recall,
        recall_at_100=recall,
        recovered_rank_summary=RecoveredRankSummary(1, median_rank, median_rank, 4),
    )


if __name__ == "__main__":
    unittest.main()

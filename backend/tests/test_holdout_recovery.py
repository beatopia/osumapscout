"""Tests for held-out top-play recovery and anti-leakage rules."""

import unittest

from backend.app.candidates.target_maps import TargetMapSeed, select_evenly_spaced_seeds
from backend.app.recommendation.holdout_recovery import (
    TargetPlayEvidence,
    split_target_evidence,
    summarize_recovery,
)
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


if __name__ == "__main__":
    unittest.main()

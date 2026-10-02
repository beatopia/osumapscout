"""Tests for HD-normalized target-mod candidate acquisition."""

import unittest
from dataclasses import replace

from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapCandidatePool,
    TargetMapSeed,
)
from backend.app.recommendation.normalized_mod_acquisition_experiment import (
    calibrated_minimum_share,
    effective_range_eligible,
    iqr_overlaps,
    hd_family_variants,
    merge_mod_family_pools,
)
from backend.app.recommendation.preference_evidence import NumericPreferenceSummary
from backend.app.recommendation.mod_family_eligibility_experiment import (
    PlayerModCompatibility,
)


class NormalizedModAcquisitionTests(unittest.TestCase):
    def test_effective_range_requires_both_iqr_overlaps(self) -> None:
        target = NumericPreferenceSummary(4, 9.5, 9.8, 10.0, 10.0, 10.0, 9.9)
        bpm = NumericPreferenceSummary(4, 175.0, 185.0, 190.0, 200.0, 210.0, 190.0)
        player = PlayerModCompatibility(
            1, 2, "peer", 3, ("HR",), ("HR",), 0.8,
            target, bpm, None, True,
        )
        self.assertTrue(effective_range_eligible(player, target, bpm))
        far_bpm = NumericPreferenceSummary(
            4, 240.0, 250.0, 260.0, 270.0, 280.0, 260.0
        )
        self.assertFalse(
            effective_range_eligible(replace(player, effective_bpm=far_bpm), target, bpm)
        )
        self.assertFalse(effective_range_eligible(replace(player, eligible=False), target, bpm))
        self.assertTrue(iqr_overlaps(target, target))
        self.assertFalse(iqr_overlaps(None, target))

    def test_calibrated_threshold_never_demands_more_than_the_target(self) -> None:
        self.assertEqual(calibrated_minimum_share(1.0), 0.5)
        self.assertEqual(calibrated_minimum_share(0.3), 0.3)
        with self.assertRaises(ValueError):
            calibrated_minimum_share(1.1)

    def test_variants_preserve_gameplay_mod_identity(self) -> None:
        self.assertEqual(hd_family_variants(("HR",)), (("HR",), ("HD", "HR")))
        self.assertEqual(hd_family_variants(("NC",)), (("NC",), ("HD", "NC")))
        self.assertEqual(hd_family_variants(()), ((), ("HD",)))

    def test_pool_merge_deduplicates_users_and_seed_hits(self) -> None:
        seeds = (TargetMapSeed(1, 11), TargetMapSeed(2, 22))
        first = TargetMapCandidatePool(
            1, "target", seeds,
            (TargetMapCandidate(2, "two", (11, 22)), TargetMapCandidate(3, "three", (11,))),
            (), 2,
        )
        second = TargetMapCandidatePool(
            1, "target", seeds,
            (TargetMapCandidate(2, "two", (11,)), TargetMapCandidate(4, "four", (22,))),
            (), 2,
        )
        merged = merge_mod_family_pools(1, "target", seeds, (first, second))
        self.assertEqual(
            tuple((item.user_id, item.seed_beatmap_ids) for item in merged.candidates),
            ((2, (11, 22)), (3, (11,)), (4, (22,))),
        )
        self.assertEqual(merged.leaderboard_requests_made, 4)


if __name__ == "__main__":
    unittest.main()

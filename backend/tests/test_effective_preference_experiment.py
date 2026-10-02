"""Focused tests for T0055 effective osu!standard attributes."""

import unittest

from backend.app.recommendation.effective_attributes import effective_attributes
from backend.app.recommendation.effective_preference_experiment import (
    build_effective_target_profile,
)
from backend.app.recommendation.holdout_recovery import TargetPlayEvidence
from backend.app.recommendation.preference_evidence import TargetPreferenceProfile


class EffectiveAttributeTests(unittest.TestCase):
    def assert_ar(self, base: float, mods: tuple[str, ...], expected: float) -> None:
        self.assertAlmostEqual(effective_attributes(base, 180, mods).effective_ar, expected)

    def test_documented_ar_examples(self) -> None:
        self.assert_ar(9, ("HR",), 10)
        self.assert_ar(8, ("DT",), 9.666666666666668)
        self.assert_ar(9, ("HD", "HR"), 10)
        self.assert_ar(9, ("HD", "DT"), 10.333333333333334)
        self.assert_ar(9, ("HD", "HR", "DT"), 11)
        self.assert_ar(9, ("HT",), 7.666666666666667)

    def test_hr_caps_before_clock_adjustment(self) -> None:
        self.assert_ar(9, ("HR", "DT"), 11)

    def test_nc_matches_dt_and_exact_mod_tuple_is_not_rewritten(self) -> None:
        mods = ("HD", "NC")
        self.assertEqual(effective_attributes(8, 180, mods), effective_attributes(8, 180, ("HD", "DT")))
        self.assertEqual(mods, ("HD", "NC"))

    def test_ht_and_daycore_use_default_slowdown(self) -> None:
        self.assertEqual(effective_attributes(9, 180, ("HT",)).clock_rate, .75)
        self.assertEqual(effective_attributes(9, 180, ("DC",)).effective_bpm, 135)

    def test_bpm_and_non_affecting_mods(self) -> None:
        self.assertEqual(effective_attributes(9, 180, ("DT",)).effective_bpm, 270)
        self.assertEqual(effective_attributes(9, 180, ("NC",)).effective_bpm, 270)
        self.assertEqual(effective_attributes(9, 180, ("HT",)).effective_bpm, 135)
        self.assertEqual(effective_attributes(9, 180, ("HD",)), effective_attributes(9, 180, ()))

    def test_incompatible_difficulty_or_speed_mods_fail(self) -> None:
        with self.assertRaises(ValueError): effective_attributes(9, 180, ("EZ", "HR"))
        with self.assertRaises(ValueError): effective_attributes(9, 180, ("DT", "HT"))


class EffectivePreferenceTests(unittest.TestCase):
    def test_target_profile_uses_each_training_plays_actual_mods(self) -> None:
        base = TargetPreferenceProfile(1, "x", 2, None, None, None, (), (), ("DT",))
        plays = (
            TargetPlayEvidence(1, 1, None, None, None, None, 8, 180, ("DT",)),
            TargetPlayEvidence(2, 2, None, None, None, None, 9, 180, ("HR",)),
        )
        result = build_effective_target_profile(base, plays)
        self.assertEqual(result.effective_bpm.minimum, 180)
        self.assertEqual(result.effective_bpm.maximum, 270)
        self.assertEqual(dict(result.clock_rates), {1.0: 1, 1.5: 1, .75: 0})

    def test_held_out_play_cannot_affect_training_profile(self) -> None:
        base = TargetPreferenceProfile(1, "x", 1, None, None, None, (), (), ())
        training = (TargetPlayEvidence(1, 1, None, None, None, None, 8, 180, ()),)
        before = build_effective_target_profile(base, training)
        held_out = TargetPlayEvidence(2, 2, None, None, None, None, 1, 50, ("HT",))
        after = build_effective_target_profile(base, training)
        self.assertEqual(before, after)
        self.assertNotIn(held_out, training)


if __name__ == "__main__":
    unittest.main()

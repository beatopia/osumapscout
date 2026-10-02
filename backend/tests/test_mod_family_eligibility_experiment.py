"""Focused tests for gameplay-mod-family eligibility."""

import unittest

from backend.app.osu.client import OsuTopPlay
from backend.app.recommendation.holdout_recovery import TargetPlayEvidence
from backend.app.recommendation.mod_family_eligibility_experiment import (
    describe_player,
    normalize_gameplay_mods,
    target_style,
)
from backend.app.similarity.ranked_candidates import RankedSimilarPlayer


class ModNormalizationTests(unittest.TestCase):
    def test_only_hidden_is_removed(self) -> None:
        self.assertEqual(normalize_gameplay_mods(("HD", "HR")), ("HR",))
        self.assertEqual(normalize_gameplay_mods(("HR",)), ("HR",))
        self.assertEqual(normalize_gameplay_mods(("HD",)), ())
        self.assertEqual(normalize_gameplay_mods(("HD", "HR", "DT")), ("HR", "DT"))
        self.assertEqual(normalize_gameplay_mods(("HD", "HR", "NC")), ("HR", "NC"))
        self.assertEqual(normalize_gameplay_mods(("HR", "FL")), ("HR", "FL"))

    def test_target_style_uses_training_only_and_normalized_share(self) -> None:
        plays = tuple(self._target(position, mods) for position, mods in enumerate(
            (("HD", "HR"), ("HR",), ("HD", "HR"), ("HD", "HR", "DT")), 1
        ))
        exact, normalized, share = target_style(plays)
        self.assertEqual(exact, ("HD", "HR"))
        self.assertEqual(normalized, ("HR",))
        self.assertEqual(share, .75)

    def test_majority_and_dominant_family_are_both_required(self) -> None:
        compatible = self._player((("HD", "HR"),) * 5 + (("HR",),) * 2 + (("HD", "HR", "DT"),) * 3)
        wrong_speed = self._player((("HD", "HR", "DT"),) * 6 + (("HD", "HR"),) * 4)
        self.assertTrue(describe_player(1, compatible, ("HR",)).eligible)
        self.assertFalse(describe_player(1, wrong_speed, ("HR",)).eligible)

    @staticmethod
    def _target(position: int, mods: tuple[str, ...]) -> TargetPlayEvidence:
        return TargetPlayEvidence(position, position, None, None, None, 5, 9, 180, mods, 200)

    @staticmethod
    def _player(mods: tuple[tuple[str, ...], ...]) -> RankedSimilarPlayer:
        plays = tuple(
            OsuTopPlay(None, index, None, None, None, None, 200, None, None, value, None, None, 5, 9, 180)
            for index, value in enumerate(mods, 1)
        )
        return RankedSimilarPlayer(1, "peer", (1, 2), "recurring", len(plays), 7, .2, .3, 5, .1, .2, plays)


if __name__ == "__main__":
    unittest.main()

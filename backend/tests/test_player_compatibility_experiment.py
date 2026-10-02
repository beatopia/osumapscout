"""Focused tests for the offline T0049 compatibility experiment."""

import unittest
from backend.app.osu.client import OsuTopPlay
from backend.app.recommendation.holdout_recovery import TargetPlayEvidence
from backend.app.recommendation.player_compatibility_experiment import (
    _features,
    _order,
    _primary_mods,
    analyze_player_compatibility,
)
from backend.app.recommendation.preference_evidence import calculate_numeric_summary
from backend.app.similarity.ranked_candidates import RankedSimilarPlayer
from backend.tests.test_selection_expansion_analysis import _recovery


class CompatibilityFeatureTests(unittest.TestCase):
    def test_exact_mod_share_pp_quartiles_overlap_and_distance(self) -> None:
        plays = tuple(_play(("HD", "HR"), float(index)) for index in range(1, 61)) + tuple(
            _play(("HD", "DT"), float(index)) for index in range(61, 101)
        )
        target = calculate_numeric_summary((25.0, 50.0, 75.0, 100.0))
        assert target is not None
        item = _features(1, _player(1, plays), ("HD", "HR"), target)
        self.assertEqual(item.target_primary_mod_share, 0.60)
        self.assertEqual((item.pp.first_quartile, item.pp.median, item.pp.third_quartile), (25.75, 50.5, 75.25))
        self.assertTrue(item.pp_iqr_overlaps)
        self.assertEqual(item.median_pp_distance, 12.0)

    def test_pp_overlap_touch_separate_and_missing(self) -> None:
        target = calculate_numeric_summary((0.0, 10.0, 20.0))
        assert target is not None
        overlap = _features(1, _player(1, (_play((), 10.0), _play((), 20.0))), (), target)
        separated = _features(2, _player(2, (_play((), 30.0), _play((), 40.0))), (), target)
        missing = _features(3, _player(3, (_play((), None),)), (), target)
        self.assertTrue(overlap.pp_iqr_overlaps)
        self.assertFalse(separated.pp_iqr_overlaps)
        self.assertIsNone(missing.pp_iqr_overlaps)

    def test_view_lexicographic_orders_and_missing_fallback(self) -> None:
        target = calculate_numeric_summary((100.0, 200.0, 300.0))
        assert target is not None
        pool = (
            _features(1, _player(1, (_play((), None),)), ("HD", "HR"), target),
            _features(2, _player(2, (_play(("HD", "HR"), 210.0),)), ("HD", "HR"), target),
            _features(3, _player(3, (_play(("HD",), 205.0),)), ("HD", "HR"), target),
        )
        self.assertEqual([x.user_id for x in _order(pool, "mod_first")], [2, 1, 3])
        self.assertEqual([x.user_id for x in _order(pool, "pp_first")], [3, 2, 1])
        self.assertEqual([x.user_id for x in _order(pool, "compatibility_first")], [2, 3, 1])

    def test_primary_mod_tie_is_lexical(self) -> None:
        plays = (
            TargetPlayEvidence(1, 1, None, None, None, None, None, None, ("HD", "HR")),
            TargetPlayEvidence(2, 2, None, None, None, None, None, None, ("HD",)),
        )
        self.assertEqual(_primary_mods(plays), ("HD",))


class CompatibilityWorkflowTests(unittest.TestCase):
    def test_four_views_share_pool_preserve_baseline_and_use_training_only(self) -> None:
        recovery = _recovery()
        recovery.target_username = "target"
        training = tuple(
            TargetPlayEvidence(i, 9000 + i, None, None, None, 5.0, 9.0, 180.0, ("HD", "HR"), 200.0 + i)
            for i in range(1, 91)
        )
        recovery.training_plays = training
        result = analyze_player_compatibility(recovery)
        self.assertEqual([view.name for view in result.views], ["baseline", "mod_first", "pp_first", "compatibility_first"])
        baseline_ids = [player.user_id for player in recovery.ranking_result.candidates]
        self.assertEqual([item.user_id for item in result.views[0].ordered_players], baseline_ids)
        expected = set(baseline_ids)
        self.assertTrue(all({item.user_id for item in view.ordered_players} == expected for view in result.views))
        self.assertEqual(result.target_primary_mods, ("HD", "HR"))
        self.assertEqual((result.leaderboard_requests, result.top_play_requests), (5, 25))


def _play(mods: tuple[str, ...], pp: float | None) -> OsuTopPlay:
    return OsuTopPlay(None, 1, None, None, None, None, pp, None, None, mods, None, None, 5.0, 9.0, 180.0)


def _player(user_id: int, plays: tuple[OsuTopPlay, ...]) -> RankedSimilarPlayer:
    return RankedSimilarPlayer(user_id, f"p{user_id}", (), "recurring", len(plays), 1, 0.1, 0.1, 1, 0.1, 0.1, plays)


if __name__ == "__main__":
    unittest.main()

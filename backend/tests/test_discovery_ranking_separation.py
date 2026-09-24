"""Tests for separating candidate discovery from existing-map evidence."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.app.recommendation.discovery_ranking_separation import (
    aggregate_discovery_ranking_separation,
    analyze_discovery_ranking_separation,
    evaluate_discovery_ranking_separation,
)
from backend.app.recommendation.selection_expansion_analysis import analyze_selection_expansion
from backend.tests.test_selection_expansion_analysis import _play, _recovery


class DiscoveryRankingWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_acquisition_serves_all_three_views(self) -> None:
        expansion = analyze_selection_expansion(_recovery())
        selection_function = AsyncMock(return_value=expansion)

        result = await evaluate_discovery_ranking_separation(
            "target", selection_function=selection_function
        )

        selection_function.assert_awaited_once()
        self.assertEqual(result.leaderboard_requests, 5)
        self.assertEqual(result.top_play_requests, 25)
        self.assertEqual(result.total_data_requests, 30)


class DiscoveryRankingAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = analyze_discovery_ranking_separation(
            analyze_selection_expansion(_recovery())
        )

    def test_hybrid_candidate_set_equals_full_top15(self) -> None:
        self.assertTrue(self.result.candidate_sets_equal)
        self.assertEqual(self.result.new_maps_full15, 2)
        self.assertEqual(self.result.new_maps_hybrid, 2)

    def test_existing_map_evidence_is_frozen(self) -> None:
        self.assertEqual(self.result.evidence_freeze.compared_maps, 3)
        self.assertEqual(self.result.evidence_freeze.total_anomalies, 0)
        top10 = _candidate(self.result.top10, 101)
        full15 = _candidate(self.result.full15, 101)
        hybrid = _candidate(self.result.hybrid, 101)
        self.assertEqual(top10.preference_evidence.collaborative.support_count, 2)
        self.assertEqual(full15.preference_evidence.collaborative.support_count, 3)
        self.assertEqual(hybrid.preference_evidence, top10.preference_evidence)

    def test_new_map_uses_expansion_support(self) -> None:
        recovery = _recovery()
        players = list(recovery.ranking_result.candidates)
        players[13] = replace(players[13], hydrated_top_plays=(_play(104),))
        recovery = SimpleNamespace(
            **{
                **recovery.__dict__,
                "ranking_result": replace(
                    recovery.ranking_result, candidates=tuple(players)
                ),
            }
        )
        result = analyze_discovery_ranking_separation(
            analyze_selection_expansion(recovery)
        )
        full15 = _candidate(result.full15, 104)
        hybrid = _candidate(result.hybrid, 104)
        self.assertEqual(hybrid.preference_evidence, full15.preference_evidence)
        self.assertEqual(hybrid.preference_evidence.collaborative.support_count, 2)

    def test_expansion_only_heldout_map_remains_recovered(self) -> None:
        impact = next(item for item in self.result.held_out_impacts if item.beatmap_id == 104)
        self.assertIsNone(impact.top10_rank)
        self.assertIsNotNone(impact.full15_rank)
        self.assertIsNotNone(impact.hybrid_rank)
        self.assertEqual(impact.introducing_player_rank, 11)

    def test_hybrid_rank_movement_is_independent(self) -> None:
        self.assertIsNot(self.result.hybrid_movement, self.result.full15_movement)
        self.assertEqual(
            self.result.hybrid_regression.improved
            + self.result.hybrid_regression.worsened
            + self.result.hybrid_regression.unchanged,
            1,
        )

    def test_cross_split_aggregation_includes_all_views(self) -> None:
        aggregate = aggregate_discovery_ranking_separation((self.result, self.result))
        self.assertEqual(aggregate.split_count, 2)
        self.assertEqual(aggregate.top10.held_out, 6)
        self.assertEqual(aggregate.full15.recovered, 4)
        self.assertEqual(aggregate.hybrid.recovered, 4)


def _candidate(view: object, beatmap_id: int):
    return next(
        item
        for item in view.preference  # type: ignore[attr-defined]
        if item.preference_evidence.collaborative.candidate_map.beatmap_id == beatmap_id
    )


if __name__ == "__main__":
    unittest.main()

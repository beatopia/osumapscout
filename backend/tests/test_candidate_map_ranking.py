"""Tests for evidence-aware candidate-map ordering."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.app.recommendation.candidate_map_ranking import (
    evaluate_candidate_map_ranking,
    rank_candidate_map_evidence,
)
from backend.app.recommendation.candidate_maps import (
    CandidateMap,
    CandidateMapExperimentResult,
    CandidateMapSummary,
    CandidateMapSupport,
)


class CandidateMapEvidenceRankingTests(unittest.TestCase):
    def test_aggregates_distinct_supporting_players(self) -> None:
        duplicate = self._support(1, rank=1, shared=10)
        candidate_map = self._map(
            100,
            (
                duplicate,
                duplicate,
                self._support(2, rank=2, shared=8),
                self._support(3, rank=4, shared=4),
            ),
        )

        result = rank_candidate_map_evidence((candidate_map,))[0]

        self.assertEqual(result.support_count, 3)
        self.assertEqual(result.total_independent_shared_count, 22)
        self.assertAlmostEqual(result.mean_independent_shared_count, 22 / 3)
        self.assertEqual(result.best_supporting_player_rank, 1)
        self.assertAlmostEqual(result.mean_supporting_player_rank, 7 / 3)

    def test_support_remains_primary_then_total_independent(self) -> None:
        support_five_total_forty = self._map(
            10,
            tuple(self._support(index, rank=index, shared=8) for index in range(1, 6)),
        )
        support_four_total_hundred = self._map(
            20,
            tuple(self._support(index + 10, rank=index, shared=25) for index in range(1, 5)),
        )
        support_five_total_sixty = self._map(
            30,
            tuple(self._support(index + 20, rank=index, shared=12) for index in range(1, 6)),
        )

        ranked = rank_candidate_map_evidence(
            (support_five_total_forty, support_four_total_hundred, support_five_total_sixty)
        )

        self.assertEqual(
            [item.candidate_map.beatmap_id for item in ranked],
            [30, 10, 20],
        )

    def test_best_rank_then_beatmap_id_and_seed_irrelevance(self) -> None:
        better_best_rank = self._map(
            30,
            (self._support(1, rank=1, shared=10), self._support(2, rank=5, shared=10)),
        )
        worse_best_rank = self._map(
            20,
            (self._support(3, rank=2, shared=10), self._support(4, rank=4, shared=10)),
        )
        same_evidence_lower_id = self._map(
            10,
            (self._support(5, rank=2, shared=10), self._support(6, rank=4, shared=10)),
        )

        ranked = rank_candidate_map_evidence(
            (worse_best_rank, better_best_rank, same_evidence_lower_id)
        )

        self.assertEqual(
            [item.candidate_map.beatmap_id for item in ranked],
            [30, 10, 20],
        )
        self.assertFalse(hasattr(ranked[0], "seed_hit_count"))

    def test_old_and_new_ranks_and_delta_are_stable(self) -> None:
        maps = (
            self._map(1, (self._support(1, rank=1, shared=5),)),
            self._map(2, (self._support(2, rank=2, shared=20),)),
            self._map(3, (self._support(3, rank=3, shared=10),)),
        )

        first = rank_candidate_map_evidence(maps)
        second = rank_candidate_map_evidence(maps)

        self.assertEqual(first, second)
        self.assertEqual([item.candidate_map.beatmap_id for item in first], [2, 3, 1])
        by_id = {item.candidate_map.beatmap_id: item for item in first}
        self.assertEqual((by_id[2].support_only_rank, by_id[2].evidence_rank), (2, 1))
        self.assertEqual(by_id[2].rank_delta, 1)
        self.assertEqual(by_id[1].rank_delta, -2)

    def test_single_support_and_empty_pool_are_valid(self) -> None:
        single = rank_candidate_map_evidence(
            (self._map(1, (self._support(1, rank=1, shared=0),)),)
        )
        self.assertEqual(single[0].support_count, 1)
        self.assertEqual(single[0].total_independent_shared_count, 0)
        self.assertEqual(rank_candidate_map_evidence(()), ())

    @staticmethod
    def _support(user_id: int, *, rank: int, shared: int) -> CandidateMapSupport:
        return CandidateMapSupport(
            user_id=user_id,
            username=f"User{user_id}",
            similar_player_rank=rank,
            independent_shared_count=shared,
            seed_excluded_jaccard_similarity=0.0,
            seed_excluded_target_coverage=0.0,
            mods=(),
            performance_points=None,
        )

    @staticmethod
    def _map(
        beatmap_id: int,
        supports: tuple[CandidateMapSupport, ...],
    ) -> CandidateMap:
        return CandidateMap(
            beatmap_id=beatmap_id,
            artist=None,
            title=None,
            difficulty_name=None,
            star_rating=None,
            approach_rate=None,
            bpm=None,
            supports=supports,
        )


class CandidateMapRankingWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_pool_once_and_performs_no_ranking_requests(self) -> None:
        maps = (
            CandidateMapEvidenceRankingTests._map(
                1,
                (CandidateMapEvidenceRankingTests._support(1, rank=1, shared=5),),
            ),
            CandidateMapEvidenceRankingTests._map(
                2,
                (CandidateMapEvidenceRankingTests._support(2, rank=2, shared=10),),
            ),
        )
        extraction = self._extraction(maps)
        extraction_function = AsyncMock(return_value=extraction)
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(),
            get_beatmap_leaderboard_users=AsyncMock(),
        )

        result = await evaluate_candidate_map_ranking(
            "target",
            seed_count=5,
            hydration_budget=25,
            top_plays=100,
            similar_player_limit=10,
            extraction_function=extraction_function,
            osu_client=client,
        )

        extraction_function.assert_awaited_once_with(
            "target",
            seed_count=5,
            hydration_budget=25,
            top_plays=100,
            similar_player_limit=10,
            osu_client=client,
        )
        self.assertIs(result.support_only_ordering, extraction.candidate_maps)
        self.assertEqual(
            [item.candidate_map.beatmap_id for item in result.evidence_aware_ordering],
            [2, 1],
        )
        self.assertEqual(result.largest_upward_moves[0].candidate_map.beatmap_id, 2)
        self.assertEqual(result.largest_downward_moves[0].candidate_map.beatmap_id, 1)
        self.assertEqual(result.extraction.additional_extraction_requests, 0)
        client.get_top_plays_by_user_id.assert_not_awaited()
        client.get_beatmap_leaderboard_users.assert_not_awaited()

    @staticmethod
    def _extraction(
        maps: tuple[CandidateMap, ...],
    ) -> CandidateMapExperimentResult:
        support_counts = [candidate_map.support_count for candidate_map in maps]
        return CandidateMapExperimentResult(
            target_user_id=42,
            target_username="Target",
            target_top_play_count=100,
            hydration_budget=25,
            similar_players_hydrated=25,
            similar_players_selected=10,
            leaderboard_requests_made=5,
            top_play_requests_made=25,
            additional_extraction_requests=0,
            contributions=(),
            candidate_maps=maps,
            summary=CandidateMapSummary(
                candidate_map_count=len(maps),
                one_or_more_support_count=sum(value >= 1 for value in support_counts),
                two_or_more_support_count=sum(value >= 2 for value in support_counts),
                three_or_more_support_count=sum(value >= 3 for value in support_counts),
                five_or_more_support_count=sum(value >= 5 for value in support_counts),
                maximum_support_count=max(support_counts, default=0),
            ),
        )


if __name__ == "__main__":
    unittest.main()

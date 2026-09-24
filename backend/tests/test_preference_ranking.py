"""Tests for preference-aware candidate-map ordering."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.app.analysis.statistics import TopPlayStatisticsInput
from backend.app.recommendation.candidate_map_ranking import CandidateMapEvidence
from backend.app.recommendation.candidate_maps import CandidateMap, CandidateMapSupport
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    NumericCandidateEvidence,
    annotate_candidate_evidence,
    build_target_preference_profile,
)
from backend.app.recommendation.preference_ranking import (
    evaluate_preference_ranking,
    rank_candidate_map_preferences,
)


class PreferenceRankingTests(unittest.TestCase):
    def test_preference_fit_breaks_support_tie_before_independent_evidence(self) -> None:
        map_a = self._candidate(1, support=5, fit=1, independent=100)
        map_b = self._candidate(2, support=5, fit=3, independent=50)

        ranked = rank_candidate_map_preferences((map_a, map_b))

        self.assertEqual(self._ids(ranked), [2, 1])

    def test_support_remains_primary_and_existing_ranks_are_unchanged(self) -> None:
        map_a = self._candidate(1, support=6, fit=0, independent=10, evidence_rank=2)
        map_b = self._candidate(2, support=5, fit=3, independent=100, evidence_rank=1)

        ranked = rank_candidate_map_preferences((map_b, map_a))

        self.assertEqual(self._ids(ranked), [1, 2])
        self.assertEqual(map_a.collaborative.evidence_rank, 2)
        self.assertEqual(map_b.collaborative.evidence_rank, 1)

    def test_missing_metadata_produces_zero_fit_without_filtering(self) -> None:
        profile = build_target_preference_profile(
            1,
            "target",
            (self._play(5.0), self._play(5.1), self._play(5.2)),
        )
        collaborative = self._collaborative(10, support=1, independent=1)
        annotated = annotate_candidate_evidence((collaborative,), profile)

        self.assertEqual(annotated[0].attributes_within_iqr_count, 0)
        self.assertEqual(annotated[0].comparable_attribute_count, 0)
        self.assertEqual(len(rank_candidate_map_preferences(annotated)), 1)

    def test_training_profile_excludes_held_out_attribute(self) -> None:
        training = (self._play(5.0), self._play(5.1), self._play(5.2))
        held_out = self._play(7.0)

        profile = build_target_preference_profile(1, "target", training)
        leaked_profile = build_target_preference_profile(
            1, "target", training + (held_out,)
        )

        assert profile.star_rating is not None
        assert leaked_profile.star_rating is not None
        self.assertEqual(profile.star_rating.maximum, 5.2)
        self.assertEqual(profile.star_rating.third_quartile, 5.15)
        self.assertEqual(profile.top_play_count, 3)
        self.assertEqual(leaked_profile.star_rating.maximum, 7.0)

    @staticmethod
    def _play(star: float) -> TopPlayStatisticsInput:
        return TopPlayStatisticsInput(None, None, star, 9.2, 185.0, ())

    @classmethod
    def _candidate(
        cls,
        beatmap_id: int,
        *,
        support: int,
        fit: int,
        independent: int,
        evidence_rank: int = 1,
    ) -> CandidatePreferenceEvidence:
        collaborative = cls._collaborative(
            beatmap_id,
            support=support,
            independent=independent,
            evidence_rank=evidence_rank,
        )
        numeric = tuple(
            NumericCandidateEvidence(5.0, 0.0, index < fit)
            for index in range(3)
        )
        return CandidatePreferenceEvidence(
            collaborative=collaborative,
            star_rating=numeric[0],
            approach_rate=numeric[1],
            bpm=numeric[2],
            attributes_within_iqr_count=fit,
            comparable_attribute_count=3,
            exact_supporting_mod_combinations=(),
            individual_supporting_mods=(),
            supports_using_target_top_mod_combo=None,
        )

    @staticmethod
    def _collaborative(
        beatmap_id: int,
        *,
        support: int,
        independent: int,
        evidence_rank: int = 1,
    ) -> CandidateMapEvidence:
        supports = tuple(
            CandidateMapSupport(
                user_id=index,
                username=f"user{index}",
                similar_player_rank=index,
                independent_shared_count=independent // support,
                seed_excluded_jaccard_similarity=0.0,
                seed_excluded_target_coverage=0.0,
                mods=(),
                performance_points=None,
            )
            for index in range(1, support + 1)
        )
        candidate = CandidateMap(
            beatmap_id=beatmap_id,
            artist=None,
            title=None,
            difficulty_name=None,
            star_rating=None,
            approach_rate=None,
            bpm=None,
            supports=supports,
        )
        return CandidateMapEvidence(
            candidate_map=candidate,
            support_count=support,
            total_independent_shared_count=independent,
            mean_independent_shared_count=independent / support,
            best_supporting_player_rank=1,
            mean_supporting_player_rank=1.0,
            support_only_rank=evidence_rank,
            evidence_rank=evidence_rank,
        )

    @staticmethod
    def _ids(ranked: tuple) -> list[int]:
        return [
            item.preference_evidence.collaborative.candidate_map.beatmap_id
            for item in ranked
        ]


class PreferenceRankingWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_preference_pool_once_and_adds_no_requests(self) -> None:
        candidate = PreferenceRankingTests._candidate(
            1, support=2, fit=2, independent=10
        )
        evidence_result = SimpleNamespace(candidates=(candidate,))
        evidence_function = AsyncMock(return_value=evidence_result)
        client = SimpleNamespace()

        result = await evaluate_preference_ranking(
            "target",
            preference_evidence_function=evidence_function,
            osu_client=client,
        )

        evidence_function.assert_awaited_once_with(
            "target",
            seed_count=5,
            hydration_budget=25,
            top_plays=100,
            similar_player_limit=10,
            show_maps=30,
            osu_client=client,
        )
        self.assertIs(result.evidence, evidence_result)
        self.assertEqual(len(result.preference_aware_ordering), 1)
        self.assertEqual(result.additional_preference_ranking_requests, 0)


if __name__ == "__main__":
    unittest.main()

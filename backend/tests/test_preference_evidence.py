"""Tests for descriptive candidate-map preference evidence."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from backend.app.analysis.statistics import ModAcronymCount, ModCombinationCount
from backend.app.recommendation.candidate_map_ranking import (
    CandidateMapEvidence,
    CandidateMapRankingExperimentResult,
)
from backend.app.recommendation.candidate_maps import (
    CandidateMap,
    CandidateMapExperimentResult,
    CandidateMapSummary,
    CandidateMapSupport,
)
from backend.app.recommendation.preference_evidence import (
    TargetPreferenceProfile,
    annotate_candidate_maps,
    calculate_numeric_summary,
    compare_numeric_evidence,
    evaluate_preference_evidence,
    summarize_mods,
    summarize_preference_pool,
)
from backend.app.similarity.overlap import TargetTopPlaysEmptyError


class NumericPreferenceTests(unittest.TestCase):
    def test_odd_even_and_missing_numeric_summaries(self) -> None:
        odd = calculate_numeric_summary([1, 2, 3, 4, 5, None])
        even = calculate_numeric_summary([1, 2, 3, 4])

        assert odd is not None
        self.assertEqual(
            (odd.minimum, odd.first_quartile, odd.median, odd.third_quartile, odd.maximum, odd.mean),
            (1, 2, 3, 4, 5, 3),
        )
        assert even is not None
        self.assertEqual(
            (even.first_quartile, even.median, even.third_quartile),
            (1.75, 2.5, 3.25),
        )
        self.assertIsNone(calculate_numeric_summary([None, None]))

    def test_delta_inclusive_iqr_and_missing_metadata(self) -> None:
        target = calculate_numeric_summary([9.2, 9.2, 9.8, 10.0, 10.0])
        assert target is not None
        target = type(target)(7, 9.0, 9.2, 9.5, 10.0, 10.2, 9.5)

        self.assertEqual(compare_numeric_evidence(10.0, target).delta_from_target_median, 0.5)
        for value in (9.2, 9.7, 10.0):
            self.assertTrue(compare_numeric_evidence(value, target).within_target_iqr)
        self.assertFalse(compare_numeric_evidence(10.1, target).within_target_iqr)
        missing = compare_numeric_evidence(None, target)
        self.assertIsNone(missing.value)
        self.assertIsNone(missing.delta_from_target_median)
        self.assertIsNone(missing.within_target_iqr)


class ModAndCandidateEvidenceTests(unittest.TestCase):
    def test_exact_and_individual_mod_semantics(self) -> None:
        exact, individual = summarize_mods(
            (("HD", "HR"), ("HD", "HR"), ("HD", "DT"), ())
        )

        self.assertEqual(
            exact,
            (
                ModCombinationCount(("HD", "HR"), 2),
                ModCombinationCount((), 1),
                ModCombinationCount(("HD", "DT"), 1),
            ),
        )
        self.assertEqual(
            individual,
            (
                ModAcronymCount("HD", 3),
                ModAcronymCount("HR", 2),
                ModAcronymCount("DT", 1),
            ),
        )

    def test_annotations_preserve_ranking_and_aggregate_mod_evidence(self) -> None:
        first = self._evidence(
            1,
            star=8.0,
            ar=10.0,
            bpm=None,
            mods=(("HD", "HR"), ("HD", "HR"), ("HD", "DT")),
        )
        second = self._evidence(2, star=6.0, ar=9.5, bpm=180.0, mods=((),))
        ranking = self._ranking((first, second))
        profile = self._profile()

        annotated = annotate_candidate_maps(ranking, profile)

        self.assertEqual(
            [item.collaborative.candidate_map.beatmap_id for item in annotated],
            [1, 2],
        )
        self.assertEqual(annotated[0].supports_using_target_top_mod_combo, 2)
        self.assertEqual(annotated[0].comparable_attribute_count, 2)
        self.assertIsNone(annotated[0].bpm.within_target_iqr)
        summary = summarize_preference_pool(annotated, profile)
        self.assertEqual(summary.candidate_map_count, 2)
        self.assertEqual(summary.bpm_metadata_count, 1)
        self.assertEqual(summary.bpm_metadata_missing_count, 1)
        self.assertEqual(sum(count for _, count in summary.iqr_count_distribution), 2)

    @staticmethod
    def _profile() -> TargetPreferenceProfile:
        numeric = calculate_numeric_summary([6.0, 7.0, 8.0])
        ar = calculate_numeric_summary([9.2, 9.5, 10.0])
        bpm = calculate_numeric_summary([170.0, 180.0, 190.0])
        return TargetPreferenceProfile(
            user_id=42,
            username="Target",
            top_play_count=3,
            star_rating=numeric,
            approach_rate=ar,
            bpm=bpm,
            exact_mod_combinations=(ModCombinationCount(("HD", "HR"), 2),),
            individual_mods=(ModAcronymCount("HD", 2), ModAcronymCount("HR", 2)),
            top_exact_mod_combination=("HD", "HR"),
        )

    @staticmethod
    def _evidence(
        beatmap_id: int,
        *,
        star: float | None,
        ar: float | None,
        bpm: float | None,
        mods: tuple[tuple[str, ...], ...],
    ) -> CandidateMapEvidence:
        supports = tuple(
            CandidateMapSupport(
                user_id=index,
                username=f"User{index}",
                similar_player_rank=index,
                independent_shared_count=10 - index,
                seed_excluded_jaccard_similarity=0.0,
                seed_excluded_target_coverage=0.0,
                mods=value,
                performance_points=None,
            )
            for index, value in enumerate(mods, start=1)
        )
        candidate_map = CandidateMap(
            beatmap_id=beatmap_id,
            artist=None,
            title=None,
            difficulty_name=None,
            star_rating=star,
            approach_rate=ar,
            bpm=bpm,
            supports=supports,
        )
        return CandidateMapEvidence(
            candidate_map=candidate_map,
            support_count=len(supports),
            total_independent_shared_count=sum(item.independent_shared_count for item in supports),
            mean_independent_shared_count=1.0,
            best_supporting_player_rank=1,
            mean_supporting_player_rank=1.0,
            support_only_rank=beatmap_id,
            evidence_rank=beatmap_id,
        )

    @staticmethod
    def _ranking(
        evidence: tuple[CandidateMapEvidence, ...],
    ) -> CandidateMapRankingExperimentResult:
        maps = tuple(item.candidate_map for item in evidence)
        extraction = CandidateMapExperimentResult(
            target_user_id=42,
            target_username="Target",
            target_top_play_count=3,
            hydration_budget=25,
            similar_players_hydrated=25,
            similar_players_selected=10,
            leaderboard_requests_made=5,
            top_play_requests_made=25,
            additional_extraction_requests=0,
            contributions=(),
            candidate_maps=maps,
            summary=CandidateMapSummary(len(maps), len(maps), 0, 0, 0, 1),
        )
        return CandidateMapRankingExperimentResult(
            extraction=extraction,
            support_only_ordering=maps,
            evidence_aware_ordering=evidence,
            largest_upward_moves=(),
            largest_downward_moves=(),
        )


class FakePreferenceSession:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.calls = 0

    def __enter__(self) -> "FakePreferenceSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        self.calls += 1
        if self.calls == 1:
            target = SimpleNamespace(user_id=42, username="Target")
            return SimpleNamespace(one_or_none=lambda: target)
        return SimpleNamespace(all=lambda: self.rows)


class PreferenceEvidenceWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_profile_runs_ranking_once_and_adds_no_requests(self) -> None:
        evidence = ModAndCandidateEvidenceTests._evidence(
            1, star=6.5, ar=9.5, bpm=180.0, mods=(("HD", "HR"),)
        )
        ranking = ModAndCandidateEvidenceTests._ranking((evidence,))
        ranking_function = AsyncMock(return_value=ranking)
        rows = [
            SimpleNamespace(star_rating=6.0, approach_rate=9.2, bpm=170.0, mods=["HD", "HR"]),
            SimpleNamespace(star_rating=7.0, approach_rate=10.0, bpm=190.0, mods=["HD", "HR"]),
        ]
        client = SimpleNamespace(get_beatmap=AsyncMock(), get_top_plays_by_user_id=AsyncMock())

        result = await evaluate_preference_evidence(
            "target",
            show_maps=1,
            session_factory=lambda: FakePreferenceSession(rows),
            ranking_function=ranking_function,
            osu_client=client,
        )

        ranking_function.assert_awaited_once_with(
            "target",
            seed_count=5,
            hydration_budget=25,
            top_plays=100,
            similar_player_limit=10,
            osu_client=client,
        )
        self.assertEqual(result.target_profile.top_play_count, 2)
        self.assertEqual(result.additional_preference_requests, 0)
        client.get_beatmap.assert_not_awaited()
        client.get_top_plays_by_user_id.assert_not_awaited()

    async def test_empty_target_fails_before_ranking(self) -> None:
        ranking_function = AsyncMock()
        with self.assertRaises(TargetTopPlaysEmptyError):
            await evaluate_preference_evidence(
                "target",
                session_factory=lambda: FakePreferenceSession([]),
                ranking_function=ranking_function,
            )
        ranking_function.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

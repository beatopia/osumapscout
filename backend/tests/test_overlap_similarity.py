"""Tests for the experimental top-play overlap workflow."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from backend.app.candidates.hydration import (
    CandidateHydrationResult,
    HydratedCandidate,
)
from backend.app.osu.client import OsuTopPlay
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
    calculate_overlap_similarity,
    run_overlap_similarity_experiment,
)


class FakeSimilaritySession:
    """Read-only double for target identity and ordered beatmap rows."""

    def __init__(self, target: Any, beatmap_ids: list[int]) -> None:
        self.target = target
        self.beatmap_ids = beatmap_ids
        self.execute_calls = 0

    def __enter__(self) -> "FakeSimilaritySession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        self.execute_calls += 1
        if self.execute_calls == 1:
            return SimpleNamespace(one_or_none=lambda: self.target)
        if self.execute_calls == 2:
            rows = [SimpleNamespace(beatmap_id=value) for value in self.beatmap_ids]
            return SimpleNamespace(all=lambda: rows)
        raise AssertionError("Similarity performed an unexpected database query.")


class OverlapMetricTests(unittest.TestCase):
    def test_identical_sets_have_full_similarity(self) -> None:
        result = calculate_overlap_similarity([1, 2, 3], [1, 2, 3])

        self.assertEqual(result.shared_beatmap_count, 3)
        self.assertEqual(result.jaccard_similarity, 1.0)
        self.assertEqual(result.target_coverage, 1.0)

    def test_disjoint_sets_have_zero_similarity(self) -> None:
        result = calculate_overlap_similarity([1, 2], [3, 4])

        self.assertEqual(result.shared_beatmap_count, 0)
        self.assertEqual(result.jaccard_similarity, 0.0)
        self.assertEqual(result.target_coverage, 0.0)

    def test_partial_overlap_uses_exact_jaccard_and_coverage_formulas(self) -> None:
        result = calculate_overlap_similarity([1, 2, 3, 4], [3, 4, 5, 6])

        self.assertEqual(result.shared_beatmap_count, 2)
        self.assertAlmostEqual(result.jaccard_similarity, 2 / 6)
        self.assertEqual(result.target_coverage, 2 / 4)

    def test_duplicates_do_not_count_twice(self) -> None:
        result = calculate_overlap_similarity([1, 1, 2], [1, 1, 1, 3])

        self.assertEqual(result.target_play_count, 2)
        self.assertEqual(result.candidate_play_count, 2)
        self.assertEqual(result.shared_beatmap_count, 1)
        self.assertAlmostEqual(result.jaccard_similarity, 1 / 3)
        self.assertEqual(result.target_coverage, 1 / 2)

    def test_empty_candidate_is_valid_and_one_item_match_is_exact(self) -> None:
        empty = calculate_overlap_similarity([1], [])
        matching = calculate_overlap_similarity([1], [1])

        self.assertEqual(empty.shared_beatmap_count, 0)
        self.assertEqual(empty.jaccard_similarity, 0.0)
        self.assertEqual(empty.target_coverage, 0.0)
        self.assertEqual(matching.jaccard_similarity, 1.0)

    def test_empty_target_is_a_domain_error(self) -> None:
        with self.assertRaisesRegex(TargetTopPlaysEmptyError, "no top plays"):
            calculate_overlap_similarity([], [1])


class OverlapWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_bounded_target_and_reuses_hydration_once(self) -> None:
        session = self._session([1, 2, 999])
        hydration = AsyncMock(
            return_value=self._hydration(
                [
                    self._candidate(30, "First", ("local",), [1, 2, 3]),
                    self._candidate(10, "Second", ("ranking",), [2, 4]),
                ],
                ranking_requests=2,
                top_play_requests=2,
            )
        )

        result = await run_overlap_similarity_experiment(
            "target",
            candidate_pool_limit=12,
            hydrate_limit=2,
            comparison_top_plays=2,
            session_factory=lambda: session,
            hydration_function=hydration,
        )

        hydration.assert_awaited_once_with(
            "target",
            candidate_pool_limit=12,
            hydrate_limit=2,
            top_plays_per_candidate=2,
        )
        self.assertEqual(result.target_play_count, 2)
        self.assertEqual(result.ranking_requests_made, 2)
        self.assertEqual(result.top_play_requests_made, 2)
        self.assertEqual([item.user_id for item in result.candidates], [30, 10])
        self.assertEqual(result.candidates[0].sources, ("local",))
        self.assertEqual(result.candidates[0].candidate_play_count, 2)
        self.assertEqual(result.candidates[0].shared_beatmap_count, 2)
        self.assertEqual(session.execute_calls, 2)

    async def test_keeps_zero_play_and_zero_overlap_candidates(self) -> None:
        session = self._session([1, 2])
        hydration = AsyncMock(
            return_value=self._hydration(
                [
                    self._candidate(20, "Empty", ("ranking",), []),
                    self._candidate(10, "Disjoint", ("local",), [3]),
                ]
            )
        )

        result = await run_overlap_similarity_experiment(
            "target",
            session_factory=lambda: session,
            hydration_function=hydration,
        )

        self.assertEqual(len(result.candidates), 2)
        self.assertTrue(
            all(candidate.shared_beatmap_count == 0 for candidate in result.candidates)
        )
        self.assertEqual([candidate.user_id for candidate in result.candidates], [10, 20])

    async def test_ordering_uses_shared_then_jaccard_then_numeric_id(self) -> None:
        session = self._session([1, 2, 3])
        hydration = AsyncMock(
            return_value=self._hydration(
                [
                    self._candidate(40, "OneShared", ("ranking",), [1]),
                    self._candidate(30, "LowerJaccard", ("ranking",), [1, 2, 8, 9]),
                    self._candidate(20, "TieHigherId", ("local",), [1, 2, 8]),
                    self._candidate(10, "TieLowerId", ("local",), [1, 2, 9]),
                ]
            )
        )

        result = await run_overlap_similarity_experiment(
            "target",
            session_factory=lambda: session,
            hydration_function=hydration,
        )

        self.assertEqual(
            [candidate.user_id for candidate in result.candidates],
            [10, 20, 30, 40],
        )

    async def test_missing_target_skips_hydration(self) -> None:
        session = FakeSimilaritySession(None, [])
        hydration = AsyncMock()

        with self.assertRaisesRegex(SimilarityTargetNotFoundError, "was not found"):
            await run_overlap_similarity_experiment(
                "missing",
                session_factory=lambda: session,
                hydration_function=hydration,
            )

        hydration.assert_not_awaited()

    async def test_empty_persisted_target_skips_hydration(self) -> None:
        session = self._session([])
        hydration = AsyncMock()

        with self.assertRaisesRegex(TargetTopPlaysEmptyError, "no top plays"):
            await run_overlap_similarity_experiment(
                "target",
                session_factory=lambda: session,
                hydration_function=hydration,
            )

        hydration.assert_not_awaited()

    async def test_no_profile_fetch_persistence_or_extra_osu_work(self) -> None:
        session = self._session([1])
        hydration = AsyncMock(return_value=self._hydration([]))

        with (
            patch("backend.app.osu.client.OsuApiClient") as osu_client,
            patch("backend.app.database.persistence.persist_user_top_plays") as persist,
        ):
            result = await run_overlap_similarity_experiment(
                "target",
                session_factory=lambda: session,
                hydration_function=hydration,
            )

        self.assertEqual(result.candidates, ())
        osu_client.assert_not_called()
        persist.assert_not_called()

    async def test_comparison_depth_is_validated_before_io(self) -> None:
        session = self._session([1])
        hydration = AsyncMock()

        for invalid in (0, 101, True):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(ValueError, "1 through 100"):
                    await run_overlap_similarity_experiment(
                        "target",
                        comparison_top_plays=invalid,
                        session_factory=lambda: session,
                        hydration_function=hydration,
                    )

        self.assertEqual(session.execute_calls, 0)
        hydration.assert_not_awaited()

    @staticmethod
    def _session(beatmap_ids: list[int]) -> FakeSimilaritySession:
        return FakeSimilaritySession(
            SimpleNamespace(user_id=42, username="Target"),
            beatmap_ids,
        )

    @staticmethod
    def _hydration(
        candidates: list[HydratedCandidate],
        *,
        ranking_requests: int = 0,
        top_play_requests: int = 0,
    ) -> CandidateHydrationResult:
        return CandidateHydrationResult(
            target_user_id=42,
            target_username="Target",
            requested_candidate_pool=20,
            discovered_candidate_count=len(candidates),
            hydrated_candidates=tuple(candidates),
            ranking_requests_made=ranking_requests,
            top_play_requests_made=top_play_requests,
        )

    @staticmethod
    def _candidate(
        user_id: int,
        username: str,
        sources: tuple[str, ...],
        beatmap_ids: list[int],
    ) -> HydratedCandidate:
        return HydratedCandidate(
            user_id=user_id,
            username=username,
            sources=sources,
            top_plays=tuple(OverlapWorkflowTests._play(value) for value in beatmap_ids),
        )

    @staticmethod
    def _play(beatmap_id: int) -> OsuTopPlay:
        return OsuTopPlay(
            score_id=None,
            beatmap_id=beatmap_id,
            beatmapset_id=None,
            artist=None,
            title=None,
            difficulty_name=None,
            performance_points=None,
            accuracy=None,
            grade=None,
            mods=(),
            max_combo=None,
            played_at=None,
            star_rating=None,
            approach_rate=None,
            bpm=None,
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for budgeted similar-player candidate ranking."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapCandidatePool,
    TargetMapSeed,
)
from backend.app.osu.client import OsuApiError, OsuTopPlay
from backend.app.similarity.overlap import TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import (
    RankedCandidatesEmptyError,
    RankedSimilarPlayer,
    evaluate_ranked_candidates,
    rank_similar_players,
    select_candidates_with_budget,
    summarize_ranked_candidates,
)
from backend.app.similarity.target_map_overlap import (
    calculate_raw_and_seed_excluded_overlap,
)


class FakeRankedSession:
    def __init__(self, beatmap_ids: list[int]) -> None:
        self.beatmap_ids = beatmap_ids
        self.execute_calls = 0

    def __enter__(self) -> "FakeRankedSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        self.execute_calls += 1
        if self.execute_calls == 1:
            target = SimpleNamespace(user_id=42, username="Target")
            return SimpleNamespace(one_or_none=lambda: target)
        if self.execute_calls == 2:
            rows = [SimpleNamespace(beatmap_id=value) for value in self.beatmap_ids]
            return SimpleNamespace(all=lambda: rows)
        raise AssertionError("Unexpected database query")


class BudgetSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seeds = tuple(TargetMapSeed(index, index) for index in range(1, 4))

    def test_recurring_first_then_stratified_one_hit_fill(self) -> None:
        candidates = (
            self._candidate(1, (1, 2)),
            self._candidate(2, (2, 3)),
            self._candidate(10, (1,)),
            self._candidate(11, (1,)),
            self._candidate(20, (2,)),
            self._candidate(30, (3,)),
        )

        selected = select_candidates_with_budget(candidates, self.seeds, 5)

        self.assertEqual([item.user_id for item in selected.recurring], [1, 2])
        self.assertEqual([item.user_id for item in selected.one_hit], [10, 20, 30])

    def test_budget_smaller_or_equal_to_recurring_uses_no_one_hit(self) -> None:
        candidates = tuple(
            self._candidate(index, (1, 2)) for index in range(1, 5)
        ) + (self._candidate(10, (1,)),)

        smaller = select_candidates_with_budget(candidates, self.seeds, 2)
        exact = select_candidates_with_budget(candidates, self.seeds, 4)

        self.assertEqual([item.user_id for item in smaller.recurring], [1, 2])
        self.assertEqual(smaller.one_hit, ())
        self.assertEqual(len(exact.recurring), 4)
        self.assertEqual(exact.one_hit, ())

    def test_large_budget_shortages_missing_groups_and_determinism(self) -> None:
        one_hit_only = (
            self._candidate(10, (1,)),
            self._candidate(20, (2,)),
        )
        recurring_only = (self._candidate(1, (1, 2)),)

        first = select_candidates_with_budget(one_hit_only, self.seeds, 10)
        second = select_candidates_with_budget(one_hit_only, self.seeds, 10)
        recurring = select_candidates_with_budget(recurring_only, self.seeds, 10)

        self.assertEqual(first, second)
        self.assertEqual(len(first.one_hit), 2)
        self.assertEqual(len(recurring.recurring), 1)
        self.assertEqual(recurring.one_hit, ())

    def test_duplicate_users_are_not_selected_twice(self) -> None:
        recurring = self._candidate(1, (1, 2))
        one_hit = self._candidate(10, (1,))
        selection = select_candidates_with_budget(
            (recurring, recurring, one_hit, one_hit), self.seeds, 4
        )

        self.assertEqual(
            [item.candidate.user_id for item in selection.ordered],
            [1, 10],
        )

    @staticmethod
    def _candidate(user_id: int, seeds: tuple[int, ...]) -> TargetMapCandidate:
        return TargetMapCandidate(user_id, f"User{user_id}", seeds)


class RankingAndSummaryTests(unittest.TestCase):
    def test_ranking_uses_metrics_then_id_and_never_seed_hits(self) -> None:
        candidates = (
            self._ranked(1, 8, 0.8, 0.8, seed_hits=3),
            self._ranked(2, 12, 0.1, 0.1, seed_hits=1),
            self._ranked(5, 10, 0.4, 0.9),
            self._ranked(4, 10, 0.5, 0.1),
            self._ranked(3, 10, 0.5, 0.8),
            self._ranked(6, 10, 0.5, 0.8),
            self._ranked(7, 5, 0.9, 0.9),
        )

        ranked = rank_similar_players(candidates)

        self.assertEqual([candidate.user_id for candidate in ranked], [2, 3, 6, 4, 5, 1, 7])

    def test_summary_thresholds_median_maximum_and_group_makeup(self) -> None:
        candidates = tuple(
            self._ranked(
                index,
                shared,
                0.0,
                0.0,
                group="recurring" if index % 2 else "one_hit",
            )
            for index, shared in enumerate([15, 10, 7, 5, 2, 1, 0, 0, 0, 0, 0], start=1)
        )
        summary = summarize_ranked_candidates(candidates)

        self.assertEqual(summary.hydrated_count, 11)
        self.assertEqual(summary.zero_shared_count, 5)
        self.assertEqual(summary.one_or_more_shared_count, 6)
        self.assertEqual(summary.two_or_more_shared_count, 5)
        self.assertEqual(summary.five_or_more_shared_count, 4)
        self.assertEqual(summary.ten_or_more_shared_count, 2)
        self.assertEqual(summary.maximum_shared_count, 15)
        self.assertEqual(summary.median_shared_count, 1.0)
        self.assertEqual((summary.top_five_groups.recurring, summary.top_five_groups.one_hit), (3, 2))
        self.assertEqual((summary.top_ten_groups.recurring, summary.top_ten_groups.one_hit), (5, 5))

    @staticmethod
    def _ranked(
        user_id: int,
        shared: int,
        jaccard: float,
        coverage: float,
        *,
        seed_hits: int = 1,
        group: str = "one_hit",
    ) -> RankedSimilarPlayer:
        return RankedSimilarPlayer(
            user_id=user_id,
            username=None,
            seed_beatmap_ids=tuple(range(seed_hits)),
            acquisition_group=group,  # type: ignore[arg-type]
            candidate_play_count=100,
            raw_shared_beatmap_count=shared,
            raw_jaccard_similarity=jaccard,
            raw_target_coverage=coverage,
            seed_excluded_shared_beatmap_count=shared,
            seed_excluded_jaccard_similarity=jaccard,
            seed_excluded_target_coverage=coverage,
        )


class RankedCandidateWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquires_once_hydrates_numeric_ids_and_ranks_metrics(self) -> None:
        session = FakeRankedSession([1, 2, 3, 4])
        seeds = (TargetMapSeed(1, 1), TargetMapSeed(4, 4))
        acquisition = AsyncMock(
            return_value=self._pool(
                (
                    TargetMapCandidate(10, "Recurring", (1, 4)),
                    TargetMapCandidate(20, "OneA", (1,)),
                    TargetMapCandidate(30, "OneB", (4,)),
                ),
                seeds,
            )
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(
                side_effect=[self._plays([1, 2]), self._plays([]), self._plays([3, 4])]
            ),
            get_user_by_username=AsyncMock(),
        )

        with patch(
            "backend.app.similarity.ranked_candidates.calculate_raw_and_seed_excluded_overlap",
            wraps=calculate_raw_and_seed_excluded_overlap,
        ) as metrics:
            result = await evaluate_ranked_candidates(
                "target",
                hydration_budget=3,
                top_plays=4,
                session_factory=lambda: session,
                acquisition_function=acquisition,
                osu_client=client,
            )

        acquisition.assert_awaited_once_with("target", seed_count=5, osu_client=client)
        self.assertEqual(metrics.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in client.get_top_plays_by_user_id.await_args_list],
            [10, 20, 30],
        )
        self.assertEqual([candidate.user_id for candidate in result.candidates], [10, 30, 20])
        self.assertEqual(result.top_play_requests_made, 3)
        self.assertEqual(result.total_hydrated, 3)
        self.assertEqual(result.recurring_selected_count, 1)
        self.assertEqual(result.one_hit_selected_count, 2)
        self.assertEqual([count for _, count in result.one_hit_sample_by_seed], [1, 1])
        self.assertEqual(result.candidates[-1].candidate_play_count, 0)
        client.get_user_by_username.assert_not_awaited()

    async def test_empty_target_and_empty_pool_fail_clearly(self) -> None:
        acquisition = AsyncMock()
        with self.assertRaises(TargetTopPlaysEmptyError):
            await evaluate_ranked_candidates(
                "target",
                session_factory=lambda: FakeRankedSession([]),
                acquisition_function=acquisition,
            )
        acquisition.assert_not_awaited()

        empty = AsyncMock(return_value=self._pool((), (TargetMapSeed(1, 1),)))
        with self.assertRaises(RankedCandidatesEmptyError):
            await evaluate_ranked_candidates(
                "target",
                session_factory=lambda: FakeRankedSession([1, 2]),
                acquisition_function=empty,
                osu_client=SimpleNamespace(),
            )

    async def test_hydration_failure_returns_no_partial_result(self) -> None:
        acquisition = AsyncMock(
            return_value=self._pool(
                (TargetMapCandidate(10, "Ten", (1,)),),
                (TargetMapSeed(1, 1),),
            )
        )
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(side_effect=OsuApiError("failed"))
        )
        with self.assertRaises(CandidateHydrationError):
            await evaluate_ranked_candidates(
                "target",
                session_factory=lambda: FakeRankedSession([1, 2]),
                acquisition_function=acquisition,
                osu_client=client,
            )

    async def test_bounds_and_scope(self) -> None:
        acquisition = AsyncMock()
        for arguments in (
            {"seed_count": 0},
            {"hydration_budget": 0},
            {"hydration_budget": 51},
            {"top_plays": 101},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    await evaluate_ranked_candidates(
                        "target",
                        session_factory=lambda: self.fail("database accessed"),
                        acquisition_function=acquisition,
                        **arguments,
                    )
        acquisition.assert_not_awaited()

        with (
            patch("backend.app.candidates.discovery.discover_candidate_users") as ranking,
            patch("backend.app.database.persistence.persist_user_top_plays") as persist,
        ):
            pass
        ranking.assert_not_called()
        persist.assert_not_called()

    @staticmethod
    def _pool(
        candidates: tuple[TargetMapCandidate, ...],
        seeds: tuple[TargetMapSeed, ...],
    ) -> TargetMapCandidatePool:
        return TargetMapCandidatePool(
            target_user_id=42,
            target_username="Target",
            selected_seeds=seeds,
            candidates=candidates,
            seed_hit_distribution=(),
            leaderboard_requests_made=len(seeds),
        )

    @staticmethod
    def _plays(ids: list[int]) -> list[OsuTopPlay]:
        return [RankedCandidateWorkflowTests._play(value) for value in ids]

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

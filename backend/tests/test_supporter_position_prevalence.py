"""Tests for supporter top-play-position prevalence diagnostics."""

import unittest
from unittest.mock import AsyncMock

from backend.app.recommendation.discovery_provenance_analysis import (
    CandidateProvenance,
    ProvenanceRunResult,
    summarize_population,
)
from backend.app.recommendation.supporter_position_prevalence import (
    aggregate_results,
    analyze_prevalence,
    evaluate_supporter_position_prevalence,
    position_bucket,
    summarize_buckets,
    summarize_cumulative,
)


class PositionPrevalenceTests(unittest.TestCase):
    def test_bucket_boundaries_and_missing(self) -> None:
        expected = {
            1: "1-10", 10: "1-10", 11: "11-25", 25: "11-25",
            26: "26-50", 50: "26-50", 51: "51-75", 75: "51-75",
            76: "76-100", 100: "76-100", None: "missing",
        }
        for value, bucket in expected.items():
            self.assertEqual(position_bucket(value), bucket)

    def test_prevalence_is_two_percent(self) -> None:
        candidates = tuple(
            _observation(index, 5, index < 2) for index in range(100)
        )
        first = summarize_buckets(candidates)[0]
        self.assertEqual((first.candidates, first.positives), (100, 2))
        self.assertEqual(first.prevalence, 0.02)

    def test_cumulative_counts(self) -> None:
        candidates = (
            _observation(1, 5, True),
            _observation(2, 20, False),
            _observation(3, 40, True),
            _observation(4, 70, False),
            _observation(5, 90, True),
            _observation(6, None, True),
        )
        summaries = summarize_cumulative(candidates)
        self.assertEqual(
            [(item.candidates, item.positives) for item in summaries],
            [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3)],
        )

    def test_stratification_and_missing(self) -> None:
        result = analyze_prevalence(_run(
            "a",
            (
                _observation(1, 5, True, recurring=True, single=True),
                _observation(2, 5, False, recurring=False, single=True),
                _observation(3, 5, True, recurring=True, single=False),
                _observation(4, None, False, recurring=True, single=True),
            ),
        ))
        first = result.recurring_single[0]
        self.assertEqual((first.candidates, first.positives), (1, 1))
        missing = next(item for item in result.buckets if item.label == "missing")
        self.assertEqual((missing.candidates, missing.positives), (1, 0))
        self.assertEqual(result.single_support[0].candidates, 2)
        self.assertEqual(result.multi_support[0].candidates, 1)

    def test_targets_aggregate_independently(self) -> None:
        results = (
            analyze_prevalence(_run("a", (_observation(1, 5, True),))),
            analyze_prevalence(_run("b", (_observation(2, 20, False),))),
        )
        aggregate = aggregate_results(results)
        self.assertEqual((aggregate.candidates, aggregate.positives), (2, 1))
        self.assertEqual(
            [(item.target, item.candidates, item.positives) for item in aggregate.targets],
            [("a", 1, 1), ("b", 1, 0)],
        )


class PositionPrevalenceWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_provenance_once_and_preserves_ranks(self) -> None:
        provenance = _run("target", (_observation(1, 5, True),))
        function = AsyncMock(return_value=provenance)
        result = await evaluate_supporter_position_prevalence(
            "target", split_index=8, provenance_function=function
        )
        function.assert_awaited_once_with("target", split_index=8)
        self.assertTrue(result.provenance.ranks_unchanged)
        self.assertEqual(result.total_data_requests, 30)


def _observation(
    beatmap_id: int,
    position: int | None,
    positive: bool,
    *,
    recurring: bool = True,
    single: bool = True,
) -> CandidateProvenance:
    support_count = 1 if single else 2
    return CandidateProvenance(
        beatmap_id=beatmap_id,
        baseline_rank=beatmap_id + 1,
        target_position=beatmap_id if positive else None,
        is_positive=positive,
        support_count=support_count,
        support_structure="single_support" if single else "multi_support",
        supporter_user_ids=tuple(range(1, support_count + 1)),
        supporter_ranks=tuple(range(11, 11 + support_count)),
        best_supporter_rank=11,
        worst_supporter_rank=10 + support_count,
        mean_supporter_rank=11 if single else 11.5,
        supporter_positions=() if position is None else (position,) * support_count,
        best_supporter_position=position,
        mean_supporter_position=float(position) if position is not None else None,
        acquisition_groups=("recurring" if recurring else "one_hit",) * support_count,
        seed_hit_counts=(2 if recurring else 1,) * support_count,
        acquisition_classification="recurring_only" if recurring else "one_hit_only",
        best_position_supporter_rank=11 if position is not None else None,
        best_position_supporter_is_best_similarity_supporter=(
            True if position is not None else None
        ),
        top_play_position_range=0 if position is not None else None,
        similarity_rank_range=support_count - 1,
        hydrated_supporter_count=support_count,
        selected_discovery_supporter_count=support_count,
        peer_comparison=None,
    )


def _run(
    target: str, candidates: tuple[CandidateProvenance, ...]
) -> ProvenanceRunResult:
    positives = tuple(item for item in candidates if item.is_positive)
    others = tuple(item for item in candidates if not item.is_positive)
    return ProvenanceRunResult(
        target=target,
        split_index=8,
        candidates=candidates,
        positives=positives,
        positive_summary=summarize_population(positives),
        other_summary=summarize_population(others),
        support_rank_strata=(),
        provenance_rank_strata=(),
        supporter_rank_strata=(),
        ranks_unchanged=True,
        leaderboard_requests=5,
        top_play_requests=25,
    )


if __name__ == "__main__":
    unittest.main()

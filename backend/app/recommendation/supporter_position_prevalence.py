"""Raw held-out-positive prevalence by supporter top-play position."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.discovery_provenance_analysis import (
    CandidateProvenance,
    ProvenanceRunResult,
    evaluate_discovery_provenance,
)

PositionBucket = Literal["1-10", "11-25", "26-50", "51-75", "76-100", "missing"]
ProvenanceFunction = Callable[..., Awaitable[ProvenanceRunResult]]
SPLITS = (8, 9, 10, 11, 12)
BUCKETS: tuple[PositionBucket, ...] = (
    "1-10", "11-25", "26-50", "51-75", "76-100", "missing"
)
CUMULATIVE_LIMITS = (10, 25, 50, 75, 100)


@dataclass(frozen=True)
class PrevalenceSummary:
    label: str
    candidates: int
    positives: int
    prevalence: float | None
    prevalence_ratio: float | None


@dataclass(frozen=True)
class ExactPositionSummary:
    position: int
    candidates: int
    positives: int


@dataclass(frozen=True)
class TargetPrevalence:
    target: str
    candidates: int
    positives: int
    buckets: tuple[PrevalenceSummary, ...]


@dataclass(frozen=True)
class PrevalenceRunResult:
    provenance: ProvenanceRunResult
    buckets: tuple[PrevalenceSummary, ...]
    cumulative: tuple[PrevalenceSummary, ...]
    recurring_single: tuple[PrevalenceSummary, ...]
    single_support: tuple[PrevalenceSummary, ...]
    multi_support: tuple[PrevalenceSummary, ...]
    exact_positions: tuple[ExactPositionSummary, ...]

    @property
    def target(self) -> str:
        return self.provenance.target

    @property
    def split_index(self) -> int:
        return self.provenance.split_index

    @property
    def total_data_requests(self) -> int:
        return self.provenance.total_data_requests


@dataclass(frozen=True)
class PrevalenceAggregate:
    run_count: int
    candidates: int
    positives: int
    buckets: tuple[PrevalenceSummary, ...]
    cumulative: tuple[PrevalenceSummary, ...]
    recurring_single: tuple[PrevalenceSummary, ...]
    single_support: tuple[PrevalenceSummary, ...]
    multi_support: tuple[PrevalenceSummary, ...]
    exact_positions: tuple[ExactPositionSummary, ...]
    targets: tuple[TargetPrevalence, ...]


async def evaluate_supporter_position_prevalence(
    username: str,
    *,
    split_index: int,
    provenance_function: ProvenanceFunction = evaluate_discovery_provenance,
    osu_client: OsuApiClient | None = None,
) -> PrevalenceRunResult:
    arguments: dict[str, object] = {"split_index": split_index}
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    provenance = await provenance_function(username, **arguments)
    return analyze_prevalence(provenance)


def analyze_prevalence(provenance: ProvenanceRunResult) -> PrevalenceRunResult:
    candidates = provenance.candidates
    return PrevalenceRunResult(
        provenance=provenance,
        buckets=summarize_buckets(candidates),
        cumulative=summarize_cumulative(candidates),
        recurring_single=summarize_buckets(tuple(
            item for item in candidates
            if item.acquisition_classification == "recurring_only"
            and item.support_structure == "single_support"
        )),
        single_support=summarize_buckets(tuple(
            item for item in candidates if item.support_structure == "single_support"
        )),
        multi_support=summarize_buckets(tuple(
            item for item in candidates if item.support_structure == "multi_support"
        )),
        exact_positions=summarize_exact_positions(candidates),
    )


def position_bucket(position: int | None) -> PositionBucket:
    if position is None:
        return "missing"
    if not 1 <= position <= 100:
        raise ValueError("Supporter top-play position must be from 1 through 100.")
    if position <= 10:
        return "1-10"
    if position <= 25:
        return "11-25"
    if position <= 50:
        return "26-50"
    if position <= 75:
        return "51-75"
    return "76-100"


def summarize_buckets(
    candidates: Sequence[CandidateProvenance],
) -> tuple[PrevalenceSummary, ...]:
    overall = _prevalence(len(candidates), sum(item.is_positive for item in candidates))
    result = []
    for bucket in BUCKETS:
        selected = [
            item for item in candidates
            if position_bucket(item.best_supporter_position) == bucket
        ]
        positives = sum(item.is_positive for item in selected)
        prevalence = _prevalence(len(selected), positives)
        result.append(PrevalenceSummary(
            bucket, len(selected), positives, prevalence,
            prevalence / overall if prevalence is not None and overall else None,
        ))
    return tuple(result)


def summarize_cumulative(
    candidates: Sequence[CandidateProvenance],
) -> tuple[PrevalenceSummary, ...]:
    overall = _prevalence(len(candidates), sum(item.is_positive for item in candidates))
    result = []
    for limit in CUMULATIVE_LIMITS:
        selected = [
            item for item in candidates
            if item.best_supporter_position is not None
            and item.best_supporter_position <= limit
        ]
        positives = sum(item.is_positive for item in selected)
        prevalence = _prevalence(len(selected), positives)
        result.append(PrevalenceSummary(
            f"<={limit}", len(selected), positives, prevalence,
            prevalence / overall if prevalence is not None and overall else None,
        ))
    return tuple(result)


def summarize_exact_positions(
    candidates: Sequence[CandidateProvenance],
) -> tuple[ExactPositionSummary, ...]:
    return tuple(
        ExactPositionSummary(
            position,
            sum(item.best_supporter_position == position for item in candidates),
            sum(
                item.best_supporter_position == position and item.is_positive
                for item in candidates
            ),
        )
        for position in range(1, 101)
    )


def aggregate_results(
    results: Sequence[PrevalenceRunResult],
) -> PrevalenceAggregate:
    candidates = tuple(
        item for result in results for item in result.provenance.candidates
    )
    targets = tuple(dict.fromkeys(result.target for result in results))
    return PrevalenceAggregate(
        run_count=len(results),
        candidates=len(candidates),
        positives=sum(item.is_positive for item in candidates),
        buckets=summarize_buckets(candidates),
        cumulative=summarize_cumulative(candidates),
        recurring_single=summarize_buckets(tuple(
            item for item in candidates
            if item.acquisition_classification == "recurring_only"
            and item.support_structure == "single_support"
        )),
        single_support=summarize_buckets(tuple(
            item for item in candidates if item.support_structure == "single_support"
        )),
        multi_support=summarize_buckets(tuple(
            item for item in candidates if item.support_structure == "multi_support"
        )),
        exact_positions=summarize_exact_positions(candidates),
        targets=tuple(
            TargetPrevalence(
                target,
                sum(
                    len(result.provenance.candidates)
                    for result in results if result.target == target
                ),
                sum(
                    len(result.provenance.positives)
                    for result in results if result.target == target
                ),
                summarize_buckets(tuple(
                    item
                    for result in results if result.target == target
                    for item in result.provenance.candidates
                )),
            )
            for target in targets
        ),
    )


def _prevalence(candidates: int, positives: int) -> float | None:
    return positives / candidates if candidates else None

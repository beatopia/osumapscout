"""Measure coarse tie groups in the unchanged discovery-only ordering."""

from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.discovery_only_placement import (
    DiscoveryOnlyCandidate,
    DiscoveryOnlyPlacementResult,
    evaluate_discovery_only_placement,
)

PlacementFunction = Callable[..., Awaitable[DiscoveryOnlyPlacementResult]]


@dataclass(frozen=True)
class TieStageSummary:
    stage: int
    candidates_in_groups: int
    group_count: int
    mean_group_size: float
    median_group_size: float
    maximum_group_size: int


@dataclass(frozen=True)
class Stage4Group:
    support_count: int
    attributes_within_iqr_count: int
    total_independent_shared_count: int
    best_supporting_player_rank: int
    size: int
    minimum_rank: int
    maximum_rank: int
    rank_span: int
    star_complete: bool
    ar_complete: bool
    bpm_complete: bool
    star_distinct_values: int
    ar_distinct_values: int
    bpm_distinct_values: int
    star_varies: bool
    ar_varies: bool
    bpm_varies: bool
    has_dominance: bool
    dominated_candidates: int

    @property
    def any_continuous_variation(self) -> bool:
        return self.star_varies or self.ar_varies or self.bpm_varies

    @property
    def all_continuous_complete(self) -> bool:
        return self.star_complete and self.ar_complete and self.bpm_complete


@dataclass(frozen=True)
class EvidenceCompleteness:
    total: int
    star_available: int
    ar_available: int
    bpm_available: int
    all_three_available: int


@dataclass(frozen=True)
class QuantizationSummary:
    field: str
    distinct_values: int
    most_common: tuple[tuple[int, int], ...]
    top_five_share: float


@dataclass(frozen=True)
class PositiveTieDiagnostic:
    beatmap_id: int
    candidate_rank: int
    support_count: int
    attributes_within_iqr_count: int
    total_independent_shared_count: int
    best_supporting_player_rank: int
    group_size: int
    minimum_rank: int
    maximum_rank: int
    beatmap_id_position: int
    star_fit_position: int | None
    ar_fit_position: int | None
    bpm_fit_position: int | None
    peers_dominating: int
    peers_dominated: int

    @property
    def unresolved_rank_uncertainty(self) -> int:
        return self.maximum_rank - self.minimum_rank


@dataclass(frozen=True)
class DiscoveryTieResult:
    split_index: int
    candidate_count: int
    stages: tuple[TieStageSummary, ...]
    stage4_groups: tuple[Stage4Group, ...]
    largest_stage4_groups: tuple[Stage4Group, ...]
    beatmap_id_dependent_count: int
    beatmap_id_dependent_rate: float
    star_varying_groups: int
    ar_varying_groups: int
    bpm_varying_groups: int
    any_varying_groups: int
    identical_or_missing_groups: int
    dominance_groups: int
    dominated_candidates: int
    mean_rank_span: float
    median_rank_span: float
    maximum_rank_span: int
    completeness: EvidenceCompleteness
    quantization: tuple[QuantizationSummary, ...]
    positives: tuple[PositiveTieDiagnostic, ...]
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


async def evaluate_discovery_ties(
    username: str, *, top_plays: int = 100, holdout_count: int = 10,
    split_count: int = 5, split_index: int = 0, seed_count: int = 5,
    candidate_top_plays: int = 100,
    placement_function: PlacementFunction = evaluate_discovery_only_placement,
    osu_client: OsuApiClient | None = None,
) -> DiscoveryTieResult:
    arguments: dict[str, object] = {
        "top_plays": top_plays, "holdout_count": holdout_count,
        "split_count": split_count, "split_index": split_index,
        "seed_count": seed_count, "candidate_top_plays": candidate_top_plays,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    return analyze_discovery_ties(await placement_function(username, **arguments))


def analyze_discovery_ties(placement: DiscoveryOnlyPlacementResult) -> DiscoveryTieResult:
    candidates = placement.candidates
    stage_keys = (
        ("support_count",),
        ("support_count", "attributes_within_iqr_count"),
        ("support_count", "attributes_within_iqr_count", "total_independent_shared_count"),
        ("support_count", "attributes_within_iqr_count", "total_independent_shared_count", "best_supporting_player_rank"),
    )
    stages = tuple(_stage(index, candidates, fields) for index, fields in enumerate(stage_keys, 1))
    grouped = _groups(candidates, stage_keys[-1])
    non_singletons = [values for values in grouped.values() if len(values) > 1]
    stage4 = tuple(sorted((_stage4_group(values) for values in non_singletons), key=lambda item: (-item.size, item.minimum_rank)))
    positive_ids = {item.candidate.beatmap_id for item in placement.positives}
    positives = tuple(
        _positive(candidate, grouped[_key(candidate, stage_keys[-1])])
        for candidate in candidates if candidate.beatmap_id in positive_ids
    )
    spans = [item.rank_span for item in stage4]
    complete = EvidenceCompleteness(
        len(candidates),
        sum(item.star_delta is not None for item in candidates),
        sum(item.ar_delta is not None for item in candidates),
        sum(item.bpm_delta is not None for item in candidates),
        sum(item.star_delta is not None and item.ar_delta is not None and item.bpm_delta is not None for item in candidates),
    )
    return DiscoveryTieResult(
        placement.split_index, len(candidates), stages, stage4, stage4[:10],
        stages[-1].candidates_in_groups,
        stages[-1].candidates_in_groups / len(candidates) if candidates else 0.0,
        sum(item.star_varies for item in stage4),
        sum(item.ar_varies for item in stage4),
        sum(item.bpm_varies for item in stage4),
        sum(item.any_continuous_variation for item in stage4),
        sum(not item.any_continuous_variation for item in stage4),
        sum(item.has_dominance for item in stage4),
        sum(item.dominated_candidates for item in stage4),
        fmean(spans) if spans else 0.0,
        float(median(spans)) if spans else 0.0,
        max(spans, default=0), complete,
        tuple(_quantization(candidates, field) for field in stage_keys[-1]),
        positives, placement.leaderboard_requests, placement.top_play_requests,
    )


def dominates(left: DiscoveryOnlyCandidate, right: DiscoveryOnlyCandidate) -> bool:
    left_values = (left.star_delta, left.ar_delta, left.bpm_delta)
    right_values = (right.star_delta, right.ar_delta, right.bpm_delta)
    if any(value is None for value in left_values + right_values):
        return False
    return all(left <= right for left, right in zip(left_values, right_values)) and any(
        left < right for left, right in zip(left_values, right_values)
    )


def _groups(candidates: Sequence[DiscoveryOnlyCandidate], fields: Sequence[str]) -> dict[tuple[int, ...], list[DiscoveryOnlyCandidate]]:
    result: dict[tuple[int, ...], list[DiscoveryOnlyCandidate]] = defaultdict(list)
    for candidate in candidates:
        result[_key(candidate, fields)].append(candidate)
    return result


def _key(candidate: DiscoveryOnlyCandidate, fields: Sequence[str]) -> tuple[int, ...]:
    return tuple(getattr(candidate, field) for field in fields)


def _stage(stage: int, candidates: Sequence[DiscoveryOnlyCandidate], fields: Sequence[str]) -> TieStageSummary:
    sizes = [len(values) for values in _groups(candidates, fields).values() if len(values) > 1]
    return TieStageSummary(stage, sum(sizes), len(sizes), fmean(sizes) if sizes else 0.0,
                           float(median(sizes)) if sizes else 0.0, max(sizes, default=0))


def _stage4_group(values: Sequence[DiscoveryOnlyCandidate]) -> Stage4Group:
    ordered = sorted(values, key=lambda item: item.rank)
    distinct = [_distinct(values, field) for field in ("star_delta", "ar_delta", "bpm_delta")]
    dominated = {item.beatmap_id for item in values if any(dominates(peer, item) for peer in values)}
    return Stage4Group(
        ordered[0].support_count, ordered[0].attributes_within_iqr_count,
        ordered[0].total_independent_shared_count, ordered[0].best_supporting_player_rank,
        len(values), ordered[0].rank, ordered[-1].rank,
        ordered[-1].rank - ordered[0].rank + 1,
        all(item.star_delta is not None for item in values),
        all(item.ar_delta is not None for item in values),
        all(item.bpm_delta is not None for item in values),
        distinct[0], distinct[1], distinct[2],
        distinct[0] > 1, distinct[1] > 1, distinct[2] > 1,
        bool(dominated), len(dominated),
    )


def _distinct(values: Sequence[DiscoveryOnlyCandidate], field: str) -> int:
    return len({abs(value) for item in values if (value := getattr(item, field)) is not None})


def _fit_position(candidate: DiscoveryOnlyCandidate, peers: Sequence[DiscoveryOnlyCandidate], field: str) -> int | None:
    value = getattr(candidate, field)
    if value is None:
        return None
    available = sorted(abs(item_value) for item in peers if (item_value := getattr(item, field)) is not None)
    return available.index(abs(value)) + 1


def _positive(candidate: DiscoveryOnlyCandidate, group: Sequence[DiscoveryOnlyCandidate]) -> PositiveTieDiagnostic:
    ordered = sorted(group, key=lambda item: item.beatmap_id)
    ranks = [item.rank for item in group]
    return PositiveTieDiagnostic(
        candidate.beatmap_id, candidate.rank, candidate.support_count,
        candidate.attributes_within_iqr_count, candidate.total_independent_shared_count,
        candidate.best_supporting_player_rank, len(group), min(ranks), max(ranks),
        ordered.index(candidate) + 1,
        _fit_position(candidate, group, "star_delta"),
        _fit_position(candidate, group, "ar_delta"),
        _fit_position(candidate, group, "bpm_delta"),
        sum(dominates(peer, candidate) for peer in group),
        sum(dominates(candidate, peer) for peer in group),
    )


def _quantization(candidates: Sequence[DiscoveryOnlyCandidate], field: str) -> QuantizationSummary:
    counts = Counter(getattr(item, field) for item in candidates)
    common = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5])
    return QuantizationSummary(field, len(counts), common,
                               sum(count for _, count in common) / len(candidates) if candidates else 0.0)

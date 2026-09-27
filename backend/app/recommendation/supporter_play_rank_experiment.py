"""Isolated supporter top-play-position experiment for discovery-only ties."""

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.continuous_tiebreak_experiment import (
    CutoffTransitions,
    DirectionSummary,
    MovementSummary,
    RankingView,
    RemainingTieSummary,
    _groups,
    _id,
    _movement,
    _view,
    summarize_direction,
)
from backend.app.recommendation.discovery_ranking_separation import (
    DiscoveryRankingSeparationResult,
    evaluate_discovery_ranking_separation,
)
from backend.app.recommendation.holdout_recovery import calculate_split_position_sets
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate

SeparationFunction = Callable[..., Awaitable[DiscoveryRankingSeparationResult]]
HISTORICAL_SPLITS = tuple(range(8))
NEW_SPLITS = (8, 9, 10, 11, 12)
TOTAL_SPLIT_COUNT = 13
CUTOFFS = (10, 30, 50, 100)
POSITION_BUCKETS = ((1, 10), (11, 25), (26, 50), (51, 75), (76, 100))


@dataclass(frozen=True)
class SupporterPositionEvidence:
    positions: tuple[int, ...]
    best: int | None
    mean: float | None


@dataclass(frozen=True)
class PositionDistribution:
    total: int
    missing: int
    buckets: tuple[tuple[str, int], ...]
    mean: float | None
    median: float | None
    minimum: int | None
    maximum: int | None


@dataclass(frozen=True)
class PopulationComparison:
    count: int
    mean_best: float | None
    median_best: float | None
    mean_mean: float | None
    median_mean: float | None


@dataclass(frozen=True)
class SupporterPositionPositive:
    target_position: int
    beatmap_id: int
    baseline_rank: int
    experimental_rank: int
    supporter_positions: tuple[int, ...]
    best_position: int | None
    mean_position: float | None
    group_size: int
    group_minimum_rank: int
    group_maximum_rank: int
    baseline_group_position: int
    experimental_group_position: int
    fit_percentile: float
    peers_better: int
    peers_worse: int
    peers_tied: int

    @property
    def signed_change(self) -> int:
        return self.experimental_rank - self.baseline_rank


@dataclass(frozen=True)
class TargetSupporterAggregate:
    target: str
    held_out: int
    recovered: int
    positives: int
    direction: DirectionSummary
    baseline_recall_at_100: float
    experimental_recall_at_100: float


@dataclass(frozen=True)
class SupporterPositionResult:
    target: str
    split_index: int
    baseline: RankingView
    experimental: RankingView
    candidate_sets_equal: bool
    recovery_equal: bool
    outside_group_stable: bool
    movement: MovementSummary
    positives: tuple[SupporterPositionPositive, ...]
    direction: DirectionSummary
    transitions: tuple[CutoffTransitions, ...]
    before_ties: RemainingTieSummary
    after_ties: RemainingTieSummary
    distribution: PositionDistribution
    positive_population: PopulationComparison
    other_population: PopulationComparison
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


async def evaluate_supporter_play_rank(
    username: str,
    *,
    split_index: int,
    separation_function: SeparationFunction = evaluate_discovery_ranking_separation,
    osu_client: OsuApiClient | None = None,
) -> SupporterPositionResult:
    arguments: dict[str, object] = {
        "split_count": TOTAL_SPLIT_COUNT,
        "split_index": split_index,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    separation = await separation_function(username, **arguments)
    return analyze_supporter_play_rank(username, separation)


def analyze_supporter_play_rank(
    target: str, separation: DiscoveryRankingSeparationResult
) -> SupporterPositionResult:
    baseline_candidates = separation.hybrid.preference
    native_ids = {_id(item) for item in separation.top10.preference}
    discovery = tuple(
        item for item in baseline_candidates if _id(item) not in native_ids
    )
    groups = _groups(discovery)
    held_ids = tuple(item.beatmap_id for item in separation.held_out_impacts)
    baseline = _view("baseline", baseline_candidates, held_ids)
    experimental_candidates = rerank_by_supporter_position(
        baseline_candidates, groups
    )
    experimental = _view("supporter_position", experimental_candidates, held_ids)
    group_ids = {
        _id(item)
        for values in groups.values()
        if len(values) > 1
        for item in values
    }
    baseline_ranks = {_id(item): item.preference_rank for item in baseline_candidates}
    experimental_ranks = {
        _id(item): item.preference_rank for item in experimental_candidates
    }
    positives = _positive_details(separation, groups, experimental_ranks)
    positive_ids = {item.beatmap_id for item in positives}
    discovery_evidence = tuple(supporter_position_evidence(item) for item in discovery)
    return SupporterPositionResult(
        target=target,
        split_index=separation.split_index,
        baseline=baseline,
        experimental=experimental,
        candidate_sets_equal=(
            {_id(item) for item in baseline.candidates}
            == {_id(item) for item in experimental.candidates}
        ),
        recovery_equal=(
            baseline.recovery.recovered_anywhere
            == experimental.recovery.recovered_anywhere
        ),
        outside_group_stable=all(
            experimental_ranks[beatmap_id] == rank
            for beatmap_id, rank in baseline_ranks.items()
            if beatmap_id not in group_ids
        ),
        movement=_movement(
            baseline_candidates, experimental_candidates, group_ids
        ),
        positives=positives,
        direction=summarize_direction([item.signed_change for item in positives]),
        transitions=summarize_position_transitions(positives),
        before_ties=_remaining_before(groups, len(discovery)),
        after_ties=_remaining_after(groups, len(discovery)),
        distribution=summarize_distribution(discovery_evidence),
        positive_population=summarize_population(
            supporter_position_evidence(item)
            for item in discovery
            if _id(item) in positive_ids
        ),
        other_population=summarize_population(
            supporter_position_evidence(item)
            for item in discovery
            if _id(item) not in positive_ids
        ),
        leaderboard_requests=separation.leaderboard_requests,
        top_play_requests=separation.top_play_requests,
    )


def supporter_position_evidence(
    candidate: PreferenceRankedCandidate,
) -> SupporterPositionEvidence:
    positions = tuple(
        support.supporter_top_play_position
        for support in candidate.preference_evidence.collaborative.candidate_map.supports
        if support.supporter_top_play_position is not None
    )
    return SupporterPositionEvidence(
        positions=positions,
        best=min(positions, default=None),
        mean=fmean(positions) if positions else None,
    )


def rerank_by_supporter_position(
    baseline: Sequence[PreferenceRankedCandidate],
    groups: dict[tuple[int, ...], list[PreferenceRankedCandidate]],
) -> tuple[PreferenceRankedCandidate, ...]:
    replacements: dict[int, PreferenceRankedCandidate] = {}
    for values in groups.values():
        if len(values) < 2:
            continue
        slots = sorted(item.preference_rank for item in values)
        ordered = sorted(values, key=_position_sort_key)
        replacements.update(zip(slots, ordered))
    return tuple(
        PreferenceRankedCandidate(
            replacements.get(rank, item).preference_evidence, rank
        )
        for rank, item in enumerate(baseline, start=1)
    )


def summarize_distribution(
    evidence: Sequence[SupporterPositionEvidence],
) -> PositionDistribution:
    values = [item.best for item in evidence if item.best is not None]
    buckets = tuple(
        (f"{low}-{high}", sum(low <= value <= high for value in values))
        for low, high in POSITION_BUCKETS
    )
    return PositionDistribution(
        total=len(evidence),
        missing=len(evidence) - len(values),
        buckets=buckets,
        mean=fmean(values) if values else None,
        median=float(median(values)) if values else None,
        minimum=min(values, default=None),
        maximum=max(values, default=None),
    )


def summarize_population(
    evidence: Sequence[SupporterPositionEvidence],
) -> PopulationComparison:
    items = tuple(evidence)
    best = [item.best for item in items if item.best is not None]
    means = [item.mean for item in items if item.mean is not None]
    return PopulationComparison(
        count=len(items),
        mean_best=fmean(best) if best else None,
        median_best=float(median(best)) if best else None,
        mean_mean=fmean(means) if means else None,
        median_mean=float(median(means)) if means else None,
    )


def summarize_position_transitions(
    positives: Sequence[SupporterPositionPositive],
) -> tuple[CutoffTransitions, ...]:
    return tuple(
        CutoffTransitions(
            cutoff,
            sum(
                item.baseline_rank > cutoff >= item.experimental_rank
                for item in positives
            ),
            sum(
                item.baseline_rank <= cutoff < item.experimental_rank
                for item in positives
            ),
        )
        for cutoff in CUTOFFS
    )


def aggregate_target(
    target: str, results: Sequence[SupporterPositionResult]
) -> TargetSupporterAggregate:
    selected = [item for item in results if item.target == target]
    positives = [item for result in selected for item in result.positives]
    return TargetSupporterAggregate(
        target=target,
        held_out=sum(item.baseline.recovery.held_out_count for item in selected),
        recovered=sum(
            item.baseline.recovery.recovered_anywhere for item in selected
        ),
        positives=len(positives),
        direction=summarize_direction([item.signed_change for item in positives]),
        baseline_recall_at_100=fmean(
            item.baseline.recovery.recall_at_100 for item in selected
        ),
        experimental_recall_at_100=fmean(
            item.experimental.recovery.recall_at_100 for item in selected
        ),
    )


def split_position_coverage(
    target_count: int = 100, holdout_count: int = 10
) -> tuple[tuple[tuple[int, ...], ...], int]:
    result = calculate_split_position_sets(
        target_count, holdout_count, TOTAL_SPLIT_COUNT
    )
    return result.split_positions, result.unique_positions_covered


def _positive_details(
    separation: DiscoveryRankingSeparationResult,
    groups: dict[tuple[int, ...], list[PreferenceRankedCandidate]],
    experimental_ranks: dict[int, int],
) -> tuple[SupporterPositionPositive, ...]:
    impacts = {
        item.beatmap_id: item
        for item in separation.held_out_impacts
        if item.classification == "newly_recovered_by_expansion"
    }
    baseline_by_id = {
        _id(item): item for item in separation.hybrid.preference
    }
    output: list[SupporterPositionPositive] = []
    for beatmap_id, impact in impacts.items():
        item = baseline_by_id[beatmap_id]
        group = groups[_discrete_key(item)]
        baseline_order = sorted(group, key=_id)
        experimental_order = sorted(group, key=_position_sort_key)
        evidence = supporter_position_evidence(item)
        position = experimental_order.index(item) + 1
        peer_evidence = [
            supporter_position_evidence(peer) for peer in group if peer != item
        ]
        output.append(
            SupporterPositionPositive(
                target_position=impact.position,
                beatmap_id=beatmap_id,
                baseline_rank=item.preference_rank,
                experimental_rank=experimental_ranks[beatmap_id],
                supporter_positions=evidence.positions,
                best_position=evidence.best,
                mean_position=evidence.mean,
                group_size=len(group),
                group_minimum_rank=min(peer.preference_rank for peer in group),
                group_maximum_rank=max(peer.preference_rank for peer in group),
                baseline_group_position=baseline_order.index(item) + 1,
                experimental_group_position=position,
                fit_percentile=100 * (len(group) - position + 1) / len(group),
                peers_better=sum(
                    _position_sort_value(peer.best)
                    < _position_sort_value(evidence.best)
                    for peer in peer_evidence
                ),
                peers_worse=sum(
                    _position_sort_value(peer.best)
                    > _position_sort_value(evidence.best)
                    for peer in peer_evidence
                ),
                peers_tied=sum(peer.best == evidence.best for peer in peer_evidence),
            )
        )
    return tuple(output)


def _position_sort_key(
    item: PreferenceRankedCandidate,
) -> tuple[bool, int, int]:
    best = supporter_position_evidence(item).best
    return (best is None, best or 0, _id(item))


def _position_sort_value(value: int | None) -> float:
    return float(value) if value is not None else float("inf")


def _remaining_before(
    groups: dict[tuple[int, ...], list[PreferenceRankedCandidate]], total: int
) -> RemainingTieSummary:
    sizes = [len(values) for values in groups.values() if len(values) > 1]
    return RemainingTieSummary(
        len(sizes), sum(sizes), sum(sizes) / total if total else 0.0
    )


def _remaining_after(
    groups: dict[tuple[int, ...], list[PreferenceRankedCandidate]], total: int
) -> RemainingTieSummary:
    counts: Counter[tuple[tuple[int, ...], int | None]] = Counter()
    for key, values in groups.items():
        for item in values:
            counts[(key, supporter_position_evidence(item).best)] += 1
    sizes = [value for value in counts.values() if value > 1]
    return RemainingTieSummary(
        len(sizes), sum(sizes), sum(sizes) / total if total else 0.0
    )


def _discrete_key(item: PreferenceRankedCandidate) -> tuple[int, ...]:
    evidence = item.preference_evidence
    collaborative = evidence.collaborative
    return (
        collaborative.support_count,
        evidence.attributes_within_iqr_count,
        collaborative.total_independent_shared_count,
        collaborative.best_supporting_player_rank,
    )

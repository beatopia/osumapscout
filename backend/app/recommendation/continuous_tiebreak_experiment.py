"""Test one continuous preference field at a time inside discovery-only ties."""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Literal

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.discovery_ranking_separation import (
    DiscoveryRankingSeparationResult,
    evaluate_discovery_ranking_separation,
)
from backend.app.recommendation.holdout_recovery import OrderingRecoverySummary, summarize_recovery
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate

Field = Literal["star", "ar", "bpm"]
SeparationFunction = Callable[..., Awaitable[DiscoveryRankingSeparationResult]]
FIELDS: tuple[Field, ...] = ("star", "ar", "bpm")
CUTOFFS = (10, 30, 50, 100)


@dataclass(frozen=True)
class RankingView:
    name: str
    candidates: tuple[PreferenceRankedCandidate, ...]
    recovery: OrderingRecoverySummary


@dataclass(frozen=True)
class MovementSummary:
    mean_absolute: float
    median_absolute: float
    maximum_absolute: int


@dataclass(frozen=True)
class RemainingTieSummary:
    groups: int
    candidates: int
    candidate_rate: float


@dataclass(frozen=True)
class PositiveMovement:
    target_position: int
    beatmap_id: int
    baseline_rank: int
    star_rank: int
    ar_rank: int
    bpm_rank: int
    group_size: int
    group_minimum_rank: int
    group_maximum_rank: int
    star_delta: float | None
    ar_delta: float | None
    bpm_delta: float | None
    support_count: int
    attributes_within_iqr_count: int
    total_independent_shared_count: int
    best_supporting_player_rank: int
    baseline_group_position: int
    star_group_position: int
    star_fit_percentile: float | None
    peers_with_smaller_star_delta: int
    peers_with_larger_star_delta: int

    def signed_change(self, field: Field) -> int:
        return getattr(self, f"{field}_rank") - self.baseline_rank


@dataclass(frozen=True)
class DirectionSummary:
    improved: int
    worsened: int
    unchanged: int
    mean_signed: float | None
    median_signed: float | None
    mean_gain: float | None
    median_gain: float | None
    mean_loss: float | None
    median_loss: float | None


@dataclass(frozen=True)
class CutoffTransitions:
    cutoff: int
    entered: int
    exited: int


@dataclass(frozen=True)
class ContinuousTiebreakResult:
    target: str
    split_index: int
    baseline: RankingView
    star: RankingView
    ar: RankingView
    bpm: RankingView
    candidate_sets_equal: bool
    outside_group_stable: bool
    movements: tuple[tuple[Field, MovementSummary], ...]
    remaining_ties: tuple[tuple[Field, RemainingTieSummary], ...]
    positives: tuple[PositiveMovement, ...]
    directions: tuple[tuple[Field, DirectionSummary], ...]
    transitions: tuple[tuple[Field, tuple[CutoffTransitions, ...]], ...]
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


@dataclass(frozen=True)
class ViewAggregate:
    held_out: int
    discovery_positives: int
    mean_recall_10: float
    mean_recall_30: float
    mean_recall_50: float
    mean_recall_100: float
    mean_split_median_rank: float | None
    mean_split_mean_rank: float | None


@dataclass(frozen=True)
class ContinuousAggregate:
    completed_runs: int
    baseline: ViewAggregate
    star: ViewAggregate
    ar: ViewAggregate
    bpm: ViewAggregate
    directions: tuple[tuple[Field, DirectionSummary], ...]
    transitions: tuple[tuple[Field, tuple[CutoffTransitions, ...]], ...]


async def evaluate_continuous_tiebreak(
    username: str, *, split_index: int = 0, top_plays: int = 100,
    holdout_count: int = 10, split_count: int = 5, seed_count: int = 5,
    candidate_top_plays: int = 100,
    separation_function: SeparationFunction = evaluate_discovery_ranking_separation,
    osu_client: OsuApiClient | None = None,
) -> ContinuousTiebreakResult:
    arguments: dict[str, object] = dict(
        split_index=split_index, top_plays=top_plays, holdout_count=holdout_count,
        split_count=split_count, seed_count=seed_count,
        candidate_top_plays=candidate_top_plays,
    )
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    separation = await separation_function(username, **arguments)
    return analyze_continuous_tiebreak(username, separation)


def analyze_continuous_tiebreak(
    target: str, separation: DiscoveryRankingSeparationResult
) -> ContinuousTiebreakResult:
    baseline_candidates = separation.hybrid.preference
    native_ids = {_id(item) for item in separation.top10.preference}
    discovery = tuple(item for item in baseline_candidates if _id(item) not in native_ids)
    groups = _groups(discovery)
    held_ids = tuple(item.beatmap_id for item in separation.held_out_impacts)
    views: dict[str, RankingView] = {
        "baseline": _view("baseline", baseline_candidates, held_ids)
    }
    for field in FIELDS:
        views[field] = _view(field, _rerank(baseline_candidates, groups, field), held_ids)
    id_sets = [{_id(item) for item in view.candidates} for view in views.values()]
    positives = _positives(separation, groups, views)
    directions = tuple((field, summarize_direction([item.signed_change(field) for item in positives])) for field in FIELDS)
    transitions = tuple((field, summarize_transitions(positives, field)) for field in FIELDS)
    group_ids = {beatmap_id for values in groups.values() if len(values) > 1 for beatmap_id in map(_id, values)}
    baseline_ranks = _ranks(baseline_candidates)
    return ContinuousTiebreakResult(
        target, separation.split_index, views["baseline"], views["star"], views["ar"], views["bpm"],
        all(ids == id_sets[0] for ids in id_sets[1:]),
        all(_ranks(views[field].candidates)[beatmap_id] == rank for beatmap_id, rank in baseline_ranks.items() if beatmap_id not in group_ids for field in FIELDS),
        tuple((field, _movement(baseline_candidates, views[field].candidates, group_ids)) for field in FIELDS),
        tuple((field, _remaining(groups, field, len(discovery))) for field in FIELDS),
        positives, directions, transitions,
        separation.leaderboard_requests, separation.top_play_requests,
    )


def aggregate_continuous_results(results: Sequence[ContinuousTiebreakResult]) -> ContinuousAggregate:
    if not results:
        raise ValueError("At least one completed continuous-tiebreak result is required.")
    positives = tuple(item for result in results for item in result.positives)
    return ContinuousAggregate(
        len(results), *(_aggregate_view(results, name, len(positives)) for name in ("baseline", "star", "ar", "bpm")),
        tuple((field, summarize_direction([item.signed_change(field) for item in positives])) for field in FIELDS),
        tuple((field, summarize_transitions(positives, field)) for field in FIELDS),
    )


def summarize_direction(changes: Sequence[int]) -> DirectionSummary:
    gains = [-value for value in changes if value < 0]
    losses = [value for value in changes if value > 0]
    return DirectionSummary(
        len(gains), len(losses), sum(value == 0 for value in changes),
        fmean(changes) if changes else None, float(median(changes)) if changes else None,
        fmean(gains) if gains else None, float(median(gains)) if gains else None,
        fmean(losses) if losses else None, float(median(losses)) if losses else None,
    )


def summarize_transitions(positives: Sequence[PositiveMovement], field: Field) -> tuple[CutoffTransitions, ...]:
    return tuple(
        CutoffTransitions(cutoff,
            sum(item.baseline_rank > cutoff >= getattr(item, f"{field}_rank") for item in positives),
            sum(item.baseline_rank <= cutoff < getattr(item, f"{field}_rank") for item in positives))
        for cutoff in CUTOFFS
    )


def _rerank(baseline: Sequence[PreferenceRankedCandidate], groups: dict[tuple[int, ...], list[PreferenceRankedCandidate]], field: Field) -> tuple[PreferenceRankedCandidate, ...]:
    replacements: dict[int, PreferenceRankedCandidate] = {}
    for values in groups.values():
        if len(values) < 2:
            continue
        slots = sorted(item.preference_rank for item in values)
        ordered = sorted(values, key=lambda item: (_missing(_delta(item, field)), _value(_delta(item, field)), _id(item)))
        replacements.update(zip(slots, ordered))
    return tuple(
        PreferenceRankedCandidate(replacements.get(rank, item).preference_evidence, rank)
        for rank, item in enumerate(baseline, 1)
    )


def _groups(candidates: Sequence[PreferenceRankedCandidate]) -> dict[tuple[int, ...], list[PreferenceRankedCandidate]]:
    result: dict[tuple[int, ...], list[PreferenceRankedCandidate]] = defaultdict(list)
    for item in candidates:
        evidence = item.preference_evidence
        collab = evidence.collaborative
        result[(collab.support_count, evidence.attributes_within_iqr_count,
                collab.total_independent_shared_count, collab.best_supporting_player_rank)].append(item)
    return result


def _remaining(groups: dict[tuple[int, ...], list[PreferenceRankedCandidate]], field: Field, total: int) -> RemainingTieSummary:
    counts: dict[tuple[tuple[int, ...], float | None], int] = defaultdict(int)
    for key, values in groups.items():
        for item in values:
            counts[(key, _delta(item, field))] += 1
    sizes = [size for size in counts.values() if size > 1]
    return RemainingTieSummary(len(sizes), sum(sizes), sum(sizes) / total if total else 0.0)


def _positives(separation: DiscoveryRankingSeparationResult, groups: dict[tuple[int, ...], list[PreferenceRankedCandidate]], views: dict[str, RankingView]) -> tuple[PositiveMovement, ...]:
    impacts = {item.beatmap_id: item for item in separation.held_out_impacts if item.classification == "newly_recovered_by_expansion"}
    baseline_by_id = {_id(item): item for item in separation.hybrid.preference}
    ranks = {name: _ranks(view.candidates) for name, view in views.items()}
    output = []
    for beatmap_id, impact in impacts.items():
        item = baseline_by_id[beatmap_id]
        evidence = item.preference_evidence
        group = groups[_discrete_key(item)]
        group_ranks = [member.preference_rank for member in group]
        baseline_order = sorted(group, key=_id)
        star_order = sorted(group, key=lambda member: (
            _missing(_delta(member, "star")), _value(_delta(member, "star")), _id(member)
        ))
        star_delta = evidence.star_rating.delta_from_target_median
        smaller = sum(
            peer_delta is not None and star_delta is not None and abs(peer_delta) < abs(star_delta)
            for peer in group if (peer_delta := _delta(peer, "star")) is not None
        )
        larger = sum(
            peer_delta is not None and star_delta is not None and abs(peer_delta) > abs(star_delta)
            for peer in group if (peer_delta := _delta(peer, "star")) is not None
        )
        star_position = star_order.index(item) + 1
        output.append(PositiveMovement(
            impact.position, beatmap_id, ranks["baseline"][beatmap_id], ranks["star"][beatmap_id],
            ranks["ar"][beatmap_id], ranks["bpm"][beatmap_id], len(group), min(group_ranks), max(group_ranks),
            evidence.star_rating.delta_from_target_median,
            evidence.approach_rate.delta_from_target_median,
            evidence.bpm.delta_from_target_median,
            evidence.collaborative.support_count,
            evidence.attributes_within_iqr_count,
            evidence.collaborative.total_independent_shared_count,
            evidence.collaborative.best_supporting_player_rank,
            baseline_order.index(item) + 1, star_position,
            (100 * (len(group) - star_position + 1) / len(group)) if star_delta is not None else None,
            smaller, larger,
        ))
    return tuple(output)


def _view(name: str, candidates: Sequence[PreferenceRankedCandidate], held_ids: Sequence[int]) -> RankingView:
    ordered = tuple(candidates)
    return RankingView(name, ordered, summarize_recovery(held_ids, tuple(_id(item) for item in ordered)))


def _movement(baseline: Sequence[PreferenceRankedCandidate], experimental: Sequence[PreferenceRankedCandidate], ids: set[int]) -> MovementSummary:
    old, new = _ranks(baseline), _ranks(experimental)
    values = [abs(new[item] - old[item]) for item in ids]
    return MovementSummary(fmean(values) if values else 0.0, float(median(values)) if values else 0.0, max(values, default=0))


def _aggregate_view(results: Sequence[ContinuousTiebreakResult], name: str, positives: int) -> ViewAggregate:
    summaries = [getattr(result, name).recovery for result in results]
    ranks = [item.recovered_rank_summary for item in summaries if item.recovered_rank_summary]
    return ViewAggregate(sum(item.held_out_count for item in summaries), positives,
        fmean(item.recall_at_10 for item in summaries), fmean(item.recall_at_30 for item in summaries),
        fmean(item.recall_at_50 for item in summaries), fmean(item.recall_at_100 for item in summaries),
        fmean(item.median for item in ranks) if ranks else None, fmean(item.mean for item in ranks) if ranks else None)


def _discrete_key(item: PreferenceRankedCandidate) -> tuple[int, ...]:
    evidence = item.preference_evidence; collab = evidence.collaborative
    return (collab.support_count, evidence.attributes_within_iqr_count,
            collab.total_independent_shared_count, collab.best_supporting_player_rank)


def _delta(item: PreferenceRankedCandidate, field: Field) -> float | None:
    evidence = item.preference_evidence
    numeric = evidence.star_rating if field == "star" else evidence.approach_rate if field == "ar" else evidence.bpm
    return numeric.delta_from_target_median


def _missing(value: float | None) -> bool:
    return value is None


def _value(value: float | None) -> float:
    return abs(value) if value is not None else 0.0


def _id(item: PreferenceRankedCandidate) -> int:
    return item.preference_evidence.collaborative.candidate_map.beatmap_id


def _ranks(candidates: Sequence[PreferenceRankedCandidate]) -> dict[int, int]:
    return {_id(item): item.preference_rank for item in candidates}

"""Expanded validation of the isolated star-only discovery tie-break."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.continuous_tiebreak_experiment import (
    CutoffTransitions, DirectionSummary, MovementSummary, PositiveMovement,
    RankingView, RemainingTieSummary, _groups, _id, _movement, _positives,
    _remaining, _rerank, _view, summarize_direction, summarize_transitions,
)
from backend.app.recommendation.discovery_ranking_separation import (
    DiscoveryRankingSeparationResult, evaluate_discovery_ranking_separation,
)
from backend.app.recommendation.holdout_recovery import calculate_split_position_sets

SeparationFunction = Callable[..., Awaitable[DiscoveryRankingSeparationResult]]
HISTORICAL_SPLITS = (0, 1, 2)
NEW_SPLITS = (3, 4, 5, 6, 7)
TOTAL_SPLIT_COUNT = 8


@dataclass(frozen=True)
class StarValidationResult:
    target: str
    split_index: int
    baseline: RankingView
    star: RankingView
    candidate_sets_equal: bool
    outside_group_stable: bool
    movement: MovementSummary
    remaining_ties: RemainingTieSummary
    positives: tuple[PositiveMovement, ...]
    direction: DirectionSummary
    transitions: tuple[CutoffTransitions, ...]
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


@dataclass(frozen=True)
class PropertySummary:
    count: int
    mean_star_delta: float | None
    median_star_delta: float | None
    mean_star_percentile: float | None
    median_star_percentile: float | None
    mean_group_size: float | None
    median_group_size: float | None
    mean_baseline_position: float | None
    median_baseline_position: float | None
    mean_target_position: float | None
    median_target_position: float | None
    mean_support: float | None
    median_support: float | None
    mean_iqr: float | None
    median_iqr: float | None
    mean_independent: float | None
    median_independent: float | None
    mean_best_player: float | None
    median_best_player: float | None


@dataclass(frozen=True)
class TargetStarAggregate:
    target: str
    completed_splits: tuple[int, ...]
    held_out: int
    recovered: int
    positive_count: int
    unique_positive_count: int
    direction: DirectionSummary
    baseline_recalls: tuple[float, float, float, float]
    star_recalls: tuple[float, float, float, float]


@dataclass(frozen=True)
class StarValidationAggregate:
    run_count: int
    held_out: int
    recovered: int
    positive_count: int
    unique_positive_count: int
    direction: DirectionSummary
    improved_properties: PropertySummary
    worsened_properties: PropertySummary
    unchanged_properties: PropertySummary
    transitions: tuple[CutoffTransitions, ...]
    targets: tuple[TargetStarAggregate, ...]


async def evaluate_star_validation(
    username: str, *, split_index: int,
    separation_function: SeparationFunction = evaluate_discovery_ranking_separation,
    osu_client: OsuApiClient | None = None,
) -> StarValidationResult:
    arguments: dict[str, object] = {"split_count": TOTAL_SPLIT_COUNT, "split_index": split_index}
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    separation = await separation_function(username, **arguments)
    return analyze_star_validation(username, separation)


def analyze_star_validation(target: str, separation: DiscoveryRankingSeparationResult) -> StarValidationResult:
    baseline = separation.hybrid.preference
    native_ids = {_id(item) for item in separation.top10.preference}
    discovery = tuple(item for item in baseline if _id(item) not in native_ids)
    groups = _groups(discovery)
    held_ids = tuple(item.beatmap_id for item in separation.held_out_impacts)
    baseline_view = _view("baseline", baseline, held_ids)
    star_view = _view("star", _rerank(baseline, groups, "star"), held_ids)
    # T0039's retained positive structure includes AR/BPM rank slots. Point those
    # slots at baseline here; T0040 constructs no AR or BPM experimental ordering.
    views = {"baseline": baseline_view, "star": star_view,
             "ar": baseline_view, "bpm": baseline_view}
    positives = _positives(separation, groups, views)
    group_ids = {_id(item) for values in groups.values() if len(values) > 1 for item in values}
    old = {_id(item): item.preference_rank for item in baseline}
    new = {_id(item): item.preference_rank for item in star_view.candidates}
    return StarValidationResult(
        target, separation.split_index, baseline_view, star_view,
        {_id(item) for item in baseline_view.candidates} == {_id(item) for item in star_view.candidates},
        all(new[beatmap_id] == rank for beatmap_id, rank in old.items() if beatmap_id not in group_ids),
        _movement(baseline, star_view.candidates, group_ids),
        _remaining(groups, "star", len(discovery)), positives,
        summarize_direction([item.signed_change("star") for item in positives]),
        summarize_transitions(positives, "star"),
        separation.leaderboard_requests, separation.top_play_requests,
    )


def aggregate_star_results(results: Sequence[StarValidationResult]) -> StarValidationAggregate:
    if not results:
        raise ValueError("At least one star-validation result is required.")
    positives = tuple(item for result in results for item in result.positives)
    changes = [item.signed_change("star") for item in positives]
    targets = tuple(dict.fromkeys(result.target for result in results))
    return StarValidationAggregate(
        len(results), sum(result.baseline.recovery.held_out_count for result in results),
        sum(result.baseline.recovery.recovered_anywhere for result in results),
        len(positives), len({(result.target, item.beatmap_id) for result in results for item in result.positives}),
        summarize_direction(changes),
        summarize_properties([item for item in positives if item.signed_change("star") < 0]),
        summarize_properties([item for item in positives if item.signed_change("star") > 0]),
        summarize_properties([item for item in positives if item.signed_change("star") == 0]),
        summarize_transitions(positives, "star"),
        tuple(aggregate_target_star(target, results) for target in targets),
    )


def aggregate_target_star(target: str, results: Sequence[StarValidationResult]) -> TargetStarAggregate:
    selected = [result for result in results if result.target == target]
    positives = [item for result in selected for item in result.positives]
    def recalls(name: str) -> tuple[float, float, float, float]:
        summaries = [getattr(result, name).recovery for result in selected]
        return tuple(fmean(getattr(item, f"recall_at_{cutoff}") for item in summaries) for cutoff in (10, 30, 50, 100))  # type: ignore[return-value]
    return TargetStarAggregate(
        target, tuple(sorted(result.split_index for result in selected)),
        sum(result.baseline.recovery.held_out_count for result in selected),
        sum(result.baseline.recovery.recovered_anywhere for result in selected),
        len(positives), len({item.beatmap_id for item in positives}),
        summarize_direction([item.signed_change("star") for item in positives]),
        recalls("baseline"), recalls("star"),
    )


def summarize_properties(positives: Sequence[PositiveMovement]) -> PropertySummary:
    pairs = [
        _pair([item.star_delta for item in positives]),
        _pair([item.star_fit_percentile for item in positives]),
        _pair([item.group_size for item in positives]),
        _pair([item.baseline_group_position for item in positives]),
        _pair([item.target_position for item in positives]),
        _pair([item.support_count for item in positives]),
        _pair([item.attributes_within_iqr_count for item in positives]),
        _pair([item.total_independent_shared_count for item in positives]),
        _pair([item.best_supporting_player_rank for item in positives]),
    ]
    return PropertySummary(len(positives), *(value for pair in pairs for value in pair))


def split_position_coverage(target_count: int = 100, holdout_count: int = 10) -> tuple[tuple[tuple[int, ...], ...], int]:
    positions = calculate_split_position_sets(target_count, holdout_count, TOTAL_SPLIT_COUNT).split_positions
    return positions, len({position for split in positions for position in split})


def _pair(values: Sequence[float | int | None]) -> tuple[float | None, float | None]:
    actual = [float(value) for value in values if value is not None]
    return (fmean(actual), float(median(actual))) if actual else (None, None)

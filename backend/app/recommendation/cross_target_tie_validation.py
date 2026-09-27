"""Pure aggregation for bounded cross-target discovery-tie validation."""

from dataclasses import dataclass
from statistics import fmean, median
from collections.abc import Sequence

from backend.app.recommendation.discovery_tie_analysis import (
    DiscoveryTieResult,
    PositiveTieDiagnostic,
)

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")
TARGET_SELECTION_REASONS = {
    "molerat": "Primary target used by T0020-T0037.",
    "peppy": "Only other 100-play target already persisted before T0038.",
    "mrekk": "Fixed established osu!standard account selected before diagnostics.",
    "Vaxei": "Fixed established osu!standard account selected before diagnostics.",
    "WhiteCat": "Fixed established osu!standard account selected before diagnostics.",
}


@dataclass(frozen=True)
class TargetSplitTieSummary:
    target: str
    result: DiscoveryTieResult


@dataclass(frozen=True)
class TargetTieAggregate:
    target: str
    completed_splits: tuple[int, ...]
    candidate_count: int
    stage4_count: int
    stage4_rate: float
    stage4_group_count: int
    mean_group_size: float
    median_group_size: float
    maximum_group_size: int
    star_variation_rate: float
    ar_variation_rate: float
    bpm_variation_rate: float
    any_variation_rate: float
    star_completeness_rate: float
    ar_completeness_rate: float
    bpm_completeness_rate: float
    all_three_completeness_rate: float


@dataclass(frozen=True)
class CrossTargetTieAggregate:
    targets: tuple[TargetTieAggregate, ...]
    total_candidates: int
    total_stage4: int
    weighted_stage4_rate: float
    unweighted_mean_target_rate: float
    median_target_rate: float
    minimum_target_rate: float
    maximum_target_rate: float
    stage4_group_count: int
    mean_group_size: float
    median_group_size: float
    maximum_group_size: int
    star_variation_rate: float
    ar_variation_rate: float
    bpm_variation_rate: float
    any_variation_rate: float
    all_complete_group_rate: float
    positives: tuple[tuple[str, int, PositiveTieDiagnostic], ...]
    positive_in_tie_rate: float
    positive_dominated_rate: float
    positive_dominating_rate: float


def aggregate_target_ties(
    target: str, summaries: Sequence[TargetSplitTieSummary]
) -> TargetTieAggregate:
    selected = [item.result for item in summaries if item.target == target]
    if not selected:
        raise ValueError(f"No completed summaries for target '{target}'.")
    groups = [group for result in selected for group in result.stage4_groups]
    sizes = [group.size for group in groups]
    total = sum(result.candidate_count for result in selected)
    stage4 = sum(result.beatmap_id_dependent_count for result in selected)
    completeness_total = sum(result.completeness.total for result in selected)
    return TargetTieAggregate(
        target, tuple(sorted(result.split_index for result in selected)), total, stage4,
        stage4 / total if total else 0.0, len(groups),
        fmean(sizes) if sizes else 0.0, float(median(sizes)) if sizes else 0.0,
        max(sizes, default=0),
        _rate(sum(result.star_varying_groups for result in selected), len(groups)),
        _rate(sum(result.ar_varying_groups for result in selected), len(groups)),
        _rate(sum(result.bpm_varying_groups for result in selected), len(groups)),
        _rate(sum(result.any_varying_groups for result in selected), len(groups)),
        _rate(sum(result.completeness.star_available for result in selected), completeness_total),
        _rate(sum(result.completeness.ar_available for result in selected), completeness_total),
        _rate(sum(result.completeness.bpm_available for result in selected), completeness_total),
        _rate(sum(result.completeness.all_three_available for result in selected), completeness_total),
    )


def aggregate_cross_target_ties(
    summaries: Sequence[TargetSplitTieSummary],
) -> CrossTargetTieAggregate:
    if not summaries:
        raise ValueError("At least one completed target/split summary is required.")
    ordered_targets = tuple(dict.fromkeys(item.target for item in summaries))
    targets = tuple(aggregate_target_ties(target, summaries) for target in ordered_targets)
    results = [item.result for item in summaries]
    groups = [group for result in results for group in result.stage4_groups]
    sizes = [group.size for group in groups]
    total = sum(item.candidate_count for item in targets)
    tied = sum(item.stage4_count for item in targets)
    positives = tuple(
        (item.target, item.result.split_index, positive)
        for item in summaries for positive in item.result.positives
    )
    return CrossTargetTieAggregate(
        targets, total, tied, _rate(tied, total),
        fmean(item.stage4_rate for item in targets),
        float(median(item.stage4_rate for item in targets)),
        min(item.stage4_rate for item in targets), max(item.stage4_rate for item in targets),
        len(groups), fmean(sizes) if sizes else 0.0,
        float(median(sizes)) if sizes else 0.0, max(sizes, default=0),
        _rate(sum(item.star_varies for item in groups), len(groups)),
        _rate(sum(item.ar_varies for item in groups), len(groups)),
        _rate(sum(item.bpm_varies for item in groups), len(groups)),
        _rate(sum(item.any_continuous_variation for item in groups), len(groups)),
        _rate(sum(item.all_continuous_complete for item in groups), len(groups)),
        positives,
        _rate(sum(item[2].group_size > 1 for item in positives), len(positives)),
        _rate(sum(item[2].peers_dominating > 0 for item in positives), len(positives)),
        _rate(sum(item[2].peers_dominated > 0 for item in positives), len(positives)),
    )


def compact_summary(target: str, result: DiscoveryTieResult) -> str:
    return (
        f"TARGET_TIE_SUMMARY target={target} split={result.split_index} "
        f"candidates={result.candidate_count} stage4={result.beatmap_id_dependent_count} "
        f"stage4_rate={result.beatmap_id_dependent_rate:.6f} "
        f"groups={len(result.stage4_groups)} max_group={result.maximum_rank_span} "
        f"star_var={result.star_varying_groups} ar_var={result.ar_varying_groups} "
        f"bpm_var={result.bpm_varying_groups} any_var={result.any_varying_groups} "
        f"all_complete={sum(group.all_continuous_complete for group in result.stage4_groups)} "
        f"positives={len(result.positives)} leaderboard={result.leaderboard_requests} "
        f"top_play={result.top_play_requests} total={result.total_data_requests}"
    )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0

"""Separate expanded candidate discovery from evidence used for existing maps."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.holdout_recovery import (
    OrderingRecoverySummary,
    summarize_recovery,
)
from backend.app.recommendation.preference_evidence import CandidatePreferenceEvidence
from backend.app.recommendation.preference_ranking import (
    PreferenceRankedCandidate,
    rank_candidate_map_preferences,
)
from backend.app.recommendation.selection_expansion_analysis import (
    RankMovementSummary,
    SelectionExpansionResult,
    SelectionRankingView,
    TopNStability,
    _top_n_stability,
    evaluate_selection_expansion,
)

SelectionFunction = Callable[..., Awaitable[SelectionExpansionResult]]


@dataclass(frozen=True)
class EvidenceFreezeDiagnostics:
    compared_maps: int
    support_anomalies: int
    independent_shared_anomalies: int
    best_player_rank_anomalies: int
    preference_anomalies: int

    @property
    def total_anomalies(self) -> int:
        return (
            self.support_anomalies
            + self.independent_shared_anomalies
            + self.best_player_rank_anomalies
            + self.preference_anomalies
        )


@dataclass(frozen=True)
class HeldOutThreeViewImpact:
    beatmap_id: int
    position: int
    classification: str
    top10_rank: int | None
    full15_rank: int | None
    hybrid_rank: int | None
    introducing_player_rank: int | None


@dataclass(frozen=True)
class RegressionSummary:
    improved: int
    worsened: int
    unchanged: int
    mean_signed_change: float | None
    median_signed_change: float | None
    mean_loss: float | None
    maximum_loss: int | None


@dataclass(frozen=True)
class DiscoveryRankingSeparationResult:
    split_index: int
    top10: SelectionRankingView
    full15: SelectionRankingView
    hybrid: SelectionRankingView
    candidate_sets_equal: bool
    new_maps_full15: int
    new_maps_hybrid: int
    evidence_freeze: EvidenceFreezeDiagnostics
    full15_stability: tuple[TopNStability, ...]
    hybrid_stability: tuple[TopNStability, ...]
    full15_movement: RankMovementSummary
    hybrid_movement: RankMovementSummary
    held_out_impacts: tuple[HeldOutThreeViewImpact, ...]
    top10_recovery: OrderingRecoverySummary
    full15_recovery: OrderingRecoverySummary
    hybrid_recovery: OrderingRecoverySummary
    full15_regression: RegressionSummary
    hybrid_regression: RegressionSummary
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


@dataclass(frozen=True)
class ViewRecoveryAggregate:
    held_out: int
    recovered: int
    micro_recovery_rate: float
    mean_recall_at_10: float
    mean_recall_at_30: float
    mean_recall_at_50: float
    mean_recall_at_100: float
    mean_split_median_rank: float | None
    mean_split_mean_rank: float | None


@dataclass(frozen=True)
class DiscoveryRankingSeparationAggregate:
    split_count: int
    top10: ViewRecoveryAggregate
    full15: ViewRecoveryAggregate
    hybrid: ViewRecoveryAggregate
    mean_full15_absolute_movement: float
    mean_hybrid_absolute_movement: float
    full15_improved: int
    full15_worsened: int
    full15_unchanged: int
    hybrid_improved: int
    hybrid_worsened: int
    hybrid_unchanged: int


async def evaluate_discovery_ranking_separation(
    username: str,
    *,
    top_plays: int = 100,
    holdout_count: int = 10,
    split_count: int = 5,
    split_index: int = 0,
    seed_count: int = 5,
    candidate_top_plays: int = 100,
    selection_function: SelectionFunction = evaluate_selection_expansion,
    osu_client: OsuApiClient | None = None,
) -> DiscoveryRankingSeparationResult:
    """Acquire once through T0034, then derive all three views in memory."""
    arguments: dict[str, object] = {
        "top_plays": top_plays,
        "holdout_count": holdout_count,
        "split_count": split_count,
        "split_index": split_index,
        "seed_count": seed_count,
        "candidate_top_plays": candidate_top_plays,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    expansion = await selection_function(username, **arguments)
    return analyze_discovery_ranking_separation(expansion)


def analyze_discovery_ranking_separation(
    expansion: SelectionExpansionResult,
) -> DiscoveryRankingSeparationResult:
    top10_by_id = _by_id(expansion.top10.preference)
    full15_by_id = _by_id(expansion.top15.preference)
    introduced_ids = set(full15_by_id) - set(top10_by_id)

    # Existing candidates retain the exact top-10 evidence object. Only genuinely
    # new maps use evidence aggregated from expansion players in the full-15 view.
    hybrid_evidence = tuple(
        item.preference_evidence for item in expansion.top10.preference
    ) + tuple(
        full15_by_id[beatmap_id].preference_evidence
        for beatmap_id in sorted(introduced_ids)
    )
    hybrid_preference = rank_candidate_map_preferences(hybrid_evidence)
    hybrid = SelectionRankingView(15, tuple(
        item.collaborative for item in hybrid_evidence
    ), hybrid_preference)
    hybrid_by_id = _by_id(hybrid.preference)

    freeze = _freeze_diagnostics(top10_by_id, hybrid_by_id)
    hybrid_moves = _rank_movement(top10_by_id, hybrid_by_id)
    held_out = tuple(
        HeldOutThreeViewImpact(
            beatmap_id=item.play.beatmap_id,
            position=item.play.position,
            classification=item.classification,
            top10_rank=item.top10_rank,
            full15_rank=item.top15_rank,
            hybrid_rank=(hybrid_by_id[item.play.beatmap_id].preference_rank
                         if item.play.beatmap_id in hybrid_by_id else None),
            introducing_player_rank=item.introducing_player_rank,
        )
        for item in expansion.held_out_impacts
    )
    held_out_ids = tuple(item.beatmap_id for item in held_out)

    return DiscoveryRankingSeparationResult(
        split_index=expansion.split_index,
        top10=expansion.top10,
        full15=expansion.top15,
        hybrid=hybrid,
        candidate_sets_equal=set(full15_by_id) == set(hybrid_by_id),
        new_maps_full15=len(introduced_ids),
        new_maps_hybrid=len(set(hybrid_by_id) - set(top10_by_id)),
        evidence_freeze=freeze,
        full15_stability=expansion.top_n_stability,
        hybrid_stability=_top_n_stability(expansion.top10.preference, hybrid.preference),
        full15_movement=expansion.rank_movement,
        hybrid_movement=hybrid_moves,
        held_out_impacts=held_out,
        top10_recovery=summarize_recovery(
            held_out_ids, _ordered_ids(expansion.top10.preference)
        ),
        full15_recovery=summarize_recovery(
            held_out_ids, _ordered_ids(expansion.top15.preference)
        ),
        hybrid_recovery=summarize_recovery(held_out_ids, _ordered_ids(hybrid.preference)),
        full15_regression=_regression(held_out, "full15_rank"),
        hybrid_regression=_regression(held_out, "hybrid_rank"),
        leaderboard_requests=expansion.leaderboard_requests,
        top_play_requests=expansion.top_play_requests,
    )


def aggregate_discovery_ranking_separation(
    results: Sequence[DiscoveryRankingSeparationResult],
) -> DiscoveryRankingSeparationAggregate:
    if not results:
        raise ValueError("At least one discovery/ranking result is required.")
    return DiscoveryRankingSeparationAggregate(
        split_count=len(results),
        top10=_aggregate_view(tuple(item.top10_recovery for item in results)),
        full15=_aggregate_view(tuple(item.full15_recovery for item in results)),
        hybrid=_aggregate_view(tuple(item.hybrid_recovery for item in results)),
        mean_full15_absolute_movement=fmean(
            item.full15_movement.mean_absolute_change for item in results
        ),
        mean_hybrid_absolute_movement=fmean(
            item.hybrid_movement.mean_absolute_change for item in results
        ),
        full15_improved=sum(item.full15_regression.improved for item in results),
        full15_worsened=sum(item.full15_regression.worsened for item in results),
        full15_unchanged=sum(item.full15_regression.unchanged for item in results),
        hybrid_improved=sum(item.hybrid_regression.improved for item in results),
        hybrid_worsened=sum(item.hybrid_regression.worsened for item in results),
        hybrid_unchanged=sum(item.hybrid_regression.unchanged for item in results),
    )


def _by_id(candidates: Sequence[PreferenceRankedCandidate]) -> dict[int, PreferenceRankedCandidate]:
    return {item.preference_evidence.collaborative.candidate_map.beatmap_id: item for item in candidates}


def _ordered_ids(candidates: Sequence[PreferenceRankedCandidate]) -> tuple[int, ...]:
    return tuple(item.preference_evidence.collaborative.candidate_map.beatmap_id for item in candidates)


def _freeze_diagnostics(
    baseline: dict[int, PreferenceRankedCandidate],
    hybrid: dict[int, PreferenceRankedCandidate],
) -> EvidenceFreezeDiagnostics:
    support = independent = best = preference = 0
    for beatmap_id, old_item in baseline.items():
        old = old_item.preference_evidence
        new = hybrid[beatmap_id].preference_evidence
        support += old.collaborative.support_count != new.collaborative.support_count
        independent += old.collaborative.total_independent_shared_count != new.collaborative.total_independent_shared_count
        best += old.collaborative.best_supporting_player_rank != new.collaborative.best_supporting_player_rank
        preference += old != new
    return EvidenceFreezeDiagnostics(len(baseline), support, independent, best, preference)


def _rank_movement(
    baseline: dict[int, PreferenceRankedCandidate],
    comparison: dict[int, PreferenceRankedCandidate],
) -> RankMovementSummary:
    movements = [abs(comparison[key].preference_rank - item.preference_rank) for key, item in baseline.items()]
    return RankMovementSummary(
        fmean(movements) if movements else 0.0,
        float(median(movements)) if movements else 0.0,
        max(movements, default=0),
    )


def _regression(
    held_out: Sequence[HeldOutThreeViewImpact], comparison_field: str
) -> RegressionSummary:
    changes = []
    for item in held_out:
        comparison = getattr(item, comparison_field)
        if item.top10_rank is not None and comparison is not None:
            changes.append(comparison - item.top10_rank)
    losses = [value for value in changes if value > 0]
    return RegressionSummary(
        improved=sum(value < 0 for value in changes),
        worsened=len(losses),
        unchanged=sum(value == 0 for value in changes),
        mean_signed_change=fmean(changes) if changes else None,
        median_signed_change=float(median(changes)) if changes else None,
        mean_loss=fmean(losses) if losses else None,
        maximum_loss=max(losses, default=None),
    )


def _aggregate_view(summaries: Sequence[OrderingRecoverySummary]) -> ViewRecoveryAggregate:
    total = sum(item.held_out_count for item in summaries)
    recovered = sum(item.recovered_anywhere for item in summaries)
    rank_summaries = [item.recovered_rank_summary for item in summaries if item.recovered_rank_summary]
    return ViewRecoveryAggregate(
        total,
        recovered,
        recovered / total if total else 0.0,
        fmean(item.recall_at_10 for item in summaries),
        fmean(item.recall_at_30 for item in summaries),
        fmean(item.recall_at_50 for item in summaries),
        fmean(item.recall_at_100 for item in summaries),
        fmean(item.median for item in rank_summaries) if rank_summaries else None,
        fmean(item.mean for item in rank_summaries) if rank_summaries else None,
    )

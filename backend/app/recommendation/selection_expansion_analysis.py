"""Diagnose rank effects from selecting 15 rather than 10 hydrated players."""

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Literal

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.candidate_map_ranking import (
    CandidateMapEvidence,
    rank_candidate_map_evidence,
)
from backend.app.recommendation.candidate_maps import extract_candidate_maps
from backend.app.recommendation.holdout_recovery import (
    HoldoutRecoveryExperimentResult,
    TargetPlayEvidence,
    evaluate_holdout_recovery,
)
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    TargetPreferenceProfile,
    annotate_candidate_evidence,
)
from backend.app.recommendation.preference_ranking import (
    PreferenceRankedCandidate,
    rank_candidate_map_preferences,
)
from backend.app.similarity.ranked_candidates import RankedCandidateExperimentResult

RecoveryFunction = Callable[..., Awaitable[HoldoutRecoveryExperimentResult]]
PressureCause = Literal[
    "new_map_pressure",
    "support_inflation_pressure",
    "mixed",
    "other",
    "not_downward",
]
HeldOutClassification = Literal[
    "already_recovered",
    "newly_recovered_by_expansion",
    "still_absent",
]

HYDRATION_BUDGET = 25
TOP10_LIMIT = 10
TOP15_LIMIT = 15
TOP_N_CUTOFFS = (10, 30, 50, 100)


@dataclass(frozen=True)
class SelectionRankingView:
    selected_limit: int
    evidence: tuple[CandidateMapEvidence, ...]
    preference: tuple[PreferenceRankedCandidate, ...]


@dataclass(frozen=True)
class NewCandidateMap:
    beatmap_id: int
    support_count_top15: int
    best_supporting_player_rank: int
    attributes_within_iqr_count: int
    preference_rank_top15: int


@dataclass(frozen=True)
class ExistingMapChange:
    beatmap_id: int
    support_count_top10: int
    support_count_top15: int
    support_delta: int
    independent_shared_top10: int
    independent_shared_top15: int
    old_preference_rank: int
    new_preference_rank: int
    rank_delta: int
    pressure_cause: PressureCause
    intrinsic_preference_unchanged: bool


@dataclass(frozen=True)
class TopNStability:
    cutoff: int
    overlap_count: int
    denominator: int
    overlap_rate: float
    entering_count: int
    leaving_count: int


@dataclass(frozen=True)
class RankMovementSummary:
    mean_absolute_change: float
    median_absolute_change: float
    maximum_absolute_change: int


@dataclass(frozen=True)
class HeldOutSelectionImpact:
    play: TargetPlayEvidence
    classification: HeldOutClassification
    top10_rank: int | None
    top15_rank: int | None
    support_top10: int | None
    support_top15: int | None
    rank_delta: int | None
    introducing_player_rank: int | None


@dataclass(frozen=True)
class DirectionalRankSummary:
    count: int
    mean: float | None
    median: float | None
    maximum: int | None


@dataclass(frozen=True)
class SelectionExpansionResult:
    split_index: int
    top10: SelectionRankingView
    top15: SelectionRankingView
    candidate_count_top10: int
    candidate_count_top15: int
    intersection_count: int
    top10_only_count: int
    top15_new_count: int
    candidate_pool_growth: int
    candidate_pool_growth_rate: float
    new_candidates: tuple[NewCandidateMap, ...]
    new_map_origin_counts: tuple[tuple[int, int], ...]
    existing_map_changes: tuple[ExistingMapChange, ...]
    support_delta_distribution: tuple[tuple[int, int], ...]
    support_tier_transitions: tuple[tuple[tuple[int, int], int], ...]
    top_n_stability: tuple[TopNStability, ...]
    rank_movement: RankMovementSummary
    held_out_impacts: tuple[HeldOutSelectionImpact, ...]
    already_recovered_improved: DirectionalRankSummary
    already_recovered_worsened: DirectionalRankSummary
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


@dataclass(frozen=True)
class SelectionExpansionAggregate:
    split_count: int
    total_candidate_maps_top10: int
    total_candidate_maps_top15: int
    mean_candidate_pool_growth: float
    total_new_candidate_maps: int
    mean_top_n_overlap_rates: tuple[tuple[int, float], ...]
    mean_absolute_rank_movement: float
    selected_limit_gains: int
    already_recovered_improvements: int
    already_recovered_regressions: int
    already_recovered_unchanged: int
    still_absent: int
    mean_already_recovered_rank_delta: float | None
    median_already_recovered_rank_delta: float | None


async def evaluate_selection_expansion(
    username: str,
    *,
    top_plays: int = 100,
    holdout_count: int = 10,
    split_count: int = 5,
    split_index: int = 0,
    seed_count: int = 5,
    candidate_top_plays: int = 100,
    recovery_function: RecoveryFunction = evaluate_holdout_recovery,
    osu_client: OsuApiClient | None = None,
) -> SelectionExpansionResult:
    """Acquire and hydrate once, then compare two in-memory selections."""
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    recovery = await recovery_function(
        username,
        top_plays=top_plays,
        holdout_count=holdout_count,
        split_count=split_count,
        split_index=split_index,
        seed_count=seed_count,
        hydration_budget=HYDRATION_BUDGET,
        candidate_top_plays=candidate_top_plays,
        similar_player_limit=TOP15_LIMIT,
        osu_client=client,
    )
    return analyze_selection_expansion(recovery)


def analyze_selection_expansion(
    recovery: HoldoutRecoveryExperimentResult,
) -> SelectionExpansionResult:
    ranking = recovery.ranking_result
    profile = recovery.target_preference_profile
    if ranking is None or profile is None:
        raise ValueError("Holdout result does not retain reusable ranking evidence.")
    top10 = _build_view(ranking, profile, TOP10_LIMIT)
    top15 = _build_view(ranking, profile, TOP15_LIMIT)
    old = _preference_by_id(top10.preference)
    new = _preference_by_id(top15.preference)
    old_ids = set(old)
    new_ids = set(new)
    introduced_ids = new_ids - old_ids
    existing_changes = _existing_changes(old, new, introduced_ids)
    new_candidates = tuple(
        NewCandidateMap(
            beatmap_id=beatmap_id,
            support_count_top15=new[beatmap_id].preference_evidence.collaborative.support_count,
            best_supporting_player_rank=(
                new[beatmap_id]
                .preference_evidence.collaborative.best_supporting_player_rank
            ),
            attributes_within_iqr_count=(
                new[beatmap_id].preference_evidence.attributes_within_iqr_count
            ),
            preference_rank_top15=new[beatmap_id].preference_rank,
        )
        for beatmap_id in sorted(introduced_ids)
    )
    origin_counts = Counter(item.best_supporting_player_rank for item in new_candidates)
    support_deltas = Counter(item.support_delta for item in existing_changes)
    tiers = Counter(
        (item.support_count_top10, item.support_count_top15)
        for item in existing_changes
        if item.support_delta
    )
    absolute_moves = [abs(item.rank_delta) for item in existing_changes]
    held_out = _held_out_impacts(
        tuple(item.play for item in recovery.held_out_maps), old, new
    )
    improved = [-item.rank_delta for item in held_out if item.rank_delta is not None and item.rank_delta < 0]
    worsened = [item.rank_delta for item in held_out if item.rank_delta is not None and item.rank_delta > 0]
    growth = len(new_ids) - len(old_ids)
    return SelectionExpansionResult(
        split_index=recovery.split_index,
        top10=top10,
        top15=top15,
        candidate_count_top10=len(old_ids),
        candidate_count_top15=len(new_ids),
        intersection_count=len(old_ids & new_ids),
        top10_only_count=len(old_ids - new_ids),
        top15_new_count=len(introduced_ids),
        candidate_pool_growth=growth,
        candidate_pool_growth_rate=growth / len(old_ids) if old_ids else 0.0,
        new_candidates=new_candidates,
        new_map_origin_counts=tuple(sorted(origin_counts.items())),
        existing_map_changes=existing_changes,
        support_delta_distribution=tuple(sorted(support_deltas.items())),
        support_tier_transitions=tuple(sorted(tiers.items())),
        top_n_stability=_top_n_stability(top10.preference, top15.preference),
        rank_movement=RankMovementSummary(
            mean_absolute_change=fmean(absolute_moves) if absolute_moves else 0.0,
            median_absolute_change=float(median(absolute_moves)) if absolute_moves else 0.0,
            maximum_absolute_change=max(absolute_moves, default=0),
        ),
        held_out_impacts=held_out,
        already_recovered_improved=_directional_summary(improved),
        already_recovered_worsened=_directional_summary(worsened),
        leaderboard_requests=recovery.leaderboard_requests_made,
        top_play_requests=recovery.top_play_requests_made,
    )


def aggregate_selection_expansions(
    results: Sequence[SelectionExpansionResult],
) -> SelectionExpansionAggregate:
    if not results:
        raise ValueError("At least one selection-expansion result is required.")
    held_out = tuple(item for result in results for item in result.held_out_impacts)
    recovered_deltas = tuple(
        item.rank_delta
        for item in held_out
        if item.classification == "already_recovered" and item.rank_delta is not None
    )
    return SelectionExpansionAggregate(
        split_count=len(results),
        total_candidate_maps_top10=sum(item.candidate_count_top10 for item in results),
        total_candidate_maps_top15=sum(item.candidate_count_top15 for item in results),
        mean_candidate_pool_growth=fmean(item.candidate_pool_growth for item in results),
        total_new_candidate_maps=sum(item.top15_new_count for item in results),
        mean_top_n_overlap_rates=tuple(
            (
                cutoff,
                fmean(
                    next(x.overlap_rate for x in item.top_n_stability if x.cutoff == cutoff)
                    for item in results
                ),
            )
            for cutoff in TOP_N_CUTOFFS
        ),
        mean_absolute_rank_movement=fmean(
            item.rank_movement.mean_absolute_change for item in results
        ),
        selected_limit_gains=sum(
            item.classification == "newly_recovered_by_expansion" for item in held_out
        ),
        already_recovered_improvements=sum(
            item.classification == "already_recovered"
            and item.rank_delta is not None
            and item.rank_delta < 0
            for item in held_out
        ),
        already_recovered_regressions=sum(
            item.classification == "already_recovered"
            and item.rank_delta is not None
            and item.rank_delta > 0
            for item in held_out
        ),
        already_recovered_unchanged=sum(
            item.classification == "already_recovered" and item.rank_delta == 0
            for item in held_out
        ),
        still_absent=sum(item.classification == "still_absent" for item in held_out),
        mean_already_recovered_rank_delta=(
            fmean(recovered_deltas) if recovered_deltas else None
        ),
        median_already_recovered_rank_delta=(
            float(median(recovered_deltas)) if recovered_deltas else None
        ),
    )


def _build_view(
    ranking: RankedCandidateExperimentResult,
    profile: TargetPreferenceProfile,
    limit: int,
) -> SelectionRankingView:
    extraction = extract_candidate_maps(ranking, limit)
    evidence = rank_candidate_map_evidence(extraction.candidate_maps)
    preference = rank_candidate_map_preferences(
        annotate_candidate_evidence(evidence, profile)
    )
    return SelectionRankingView(limit, evidence, preference)


def _preference_by_id(
    candidates: Sequence[PreferenceRankedCandidate],
) -> dict[int, PreferenceRankedCandidate]:
    return {
        item.preference_evidence.collaborative.candidate_map.beatmap_id: item
        for item in candidates
    }


def _existing_changes(
    old: dict[int, PreferenceRankedCandidate],
    new: dict[int, PreferenceRankedCandidate],
    introduced_ids: set[int],
) -> tuple[ExistingMapChange, ...]:
    changes: list[ExistingMapChange] = []
    for beatmap_id, old_item in old.items():
        new_item = new[beatmap_id]
        old_evidence = old_item.preference_evidence
        new_evidence = new_item.preference_evidence
        old_collab = old_evidence.collaborative
        new_collab = new_evidence.collaborative
        rank_delta = new_item.preference_rank - old_item.preference_rank
        new_above = any(
            new[item].preference_rank < new_item.preference_rank
            for item in introduced_ids
        )
        promoted_above = any(
            other_id != beatmap_id
            and new[other_id].preference_evidence.collaborative.support_count
            > old[other_id].preference_evidence.collaborative.support_count
            and old[other_id].preference_rank > old_item.preference_rank
            and new[other_id].preference_rank < new_item.preference_rank
            for other_id in old
        )
        changes.append(
            ExistingMapChange(
                beatmap_id=beatmap_id,
                support_count_top10=old_collab.support_count,
                support_count_top15=new_collab.support_count,
                support_delta=new_collab.support_count - old_collab.support_count,
                independent_shared_top10=old_collab.total_independent_shared_count,
                independent_shared_top15=new_collab.total_independent_shared_count,
                old_preference_rank=old_item.preference_rank,
                new_preference_rank=new_item.preference_rank,
                rank_delta=rank_delta,
                pressure_cause=_pressure_cause(rank_delta, new_above, promoted_above),
                intrinsic_preference_unchanged=_intrinsic_signature(old_evidence)
                == _intrinsic_signature(new_evidence),
            )
        )
    return tuple(sorted(changes, key=lambda item: item.old_preference_rank))


def _pressure_cause(
    rank_delta: int, new_above: bool, promoted_above: bool
) -> PressureCause:
    if rank_delta <= 0:
        return "not_downward"
    if new_above and promoted_above:
        return "mixed"
    if new_above:
        return "new_map_pressure"
    if promoted_above:
        return "support_inflation_pressure"
    return "other"


def _intrinsic_signature(item: CandidatePreferenceEvidence) -> tuple[object, ...]:
    return (
        item.star_rating,
        item.approach_rate,
        item.bpm,
        item.attributes_within_iqr_count,
        item.comparable_attribute_count,
    )


def _top_n_stability(
    old: Sequence[PreferenceRankedCandidate],
    new: Sequence[PreferenceRankedCandidate],
) -> tuple[TopNStability, ...]:
    old_ids = [item.preference_evidence.collaborative.candidate_map.beatmap_id for item in old]
    new_ids = [item.preference_evidence.collaborative.candidate_map.beatmap_id for item in new]
    summaries = []
    for cutoff in TOP_N_CUTOFFS:
        old_prefix = set(old_ids[:cutoff])
        new_prefix = set(new_ids[:cutoff])
        denominator = min(cutoff, len(old_prefix), len(new_prefix))
        overlap = len(old_prefix & new_prefix)
        summaries.append(
            TopNStability(
                cutoff,
                overlap,
                denominator,
                overlap / denominator if denominator else 0.0,
                len(new_prefix - old_prefix),
                len(old_prefix - new_prefix),
            )
        )
    return tuple(summaries)


def _held_out_impacts(
    held_out: Sequence[TargetPlayEvidence],
    old: dict[int, PreferenceRankedCandidate],
    new: dict[int, PreferenceRankedCandidate],
) -> tuple[HeldOutSelectionImpact, ...]:
    impacts = []
    for play in held_out:
        old_item = old.get(play.beatmap_id)
        new_item = new.get(play.beatmap_id)
        old_rank = old_item.preference_rank if old_item else None
        new_rank = new_item.preference_rank if new_item else None
        classification: HeldOutClassification
        if old_item is not None:
            classification = "already_recovered"
        elif new_item is not None:
            classification = "newly_recovered_by_expansion"
        else:
            classification = "still_absent"
        impacts.append(
            HeldOutSelectionImpact(
                play=play,
                classification=classification,
                top10_rank=old_rank,
                top15_rank=new_rank,
                support_top10=(old_item.preference_evidence.collaborative.support_count if old_item else None),
                support_top15=(new_item.preference_evidence.collaborative.support_count if new_item else None),
                rank_delta=(new_rank - old_rank if old_rank is not None and new_rank is not None else None),
                introducing_player_rank=(
                    new_item.preference_evidence.collaborative.best_supporting_player_rank
                    if old_item is None and new_item is not None
                    else None
                ),
            )
        )
    return tuple(impacts)


def _directional_summary(values: Sequence[int]) -> DirectionalRankSummary:
    return DirectionalRankSummary(
        count=len(values),
        mean=fmean(values) if values else None,
        median=float(median(values)) if values else None,
        maximum=max(values, default=None),
    )

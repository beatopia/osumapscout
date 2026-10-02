"""Offline T0054 out-of-sample validation of the fixed 25/0 and 20/5 views."""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Literal

from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapCandidatePool,
    TargetMapSeed,
    acquire_target_map_candidate_pool,
    select_evenly_spaced_seeds,
)
from backend.app.database.connection import get_session_factory
from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.allocation_mixture_experiment import (
    AllocatedCandidate,
    AllocationViewResult,
    _placement,
    _retention,
    allocate_candidates,
    source_priority,
)
from backend.app.recommendation.candidate_acquisition_experiment import (
    HydratedDiagnostics,
    HydrationCacheClient,
    ModSeedDiagnostic,
    acquire_mod_filtered_pool,
)
from backend.app.recommendation.holdout_recovery import (
    HeldOutMapRecovery,
    HoldoutRecoveryExperimentResult,
    TargetPlayEvidence,
    _load_target_evidence,
    evaluate_holdout_recovery,
    split_target_evidence,
)
from backend.app.recommendation.player_compatibility_experiment import (
    CompatibilityFeatures,
    _features,
    _primary_mods,
    _selection_summary,
)
from backend.app.recommendation.preference_evidence import (
    NumericPreferenceSummary,
    calculate_numeric_summary,
)

ValidationViewName = Literal["25/0", "20/5"]
Comparison = Literal["improved", "worsened", "tied"]
TransitionCause = Literal[
    "target_mod_top_10",
    "target_mod_ranks_11_15",
    "changed_baseline_membership",
    "unknown_or_mixed",
]
VALIDATION_ALLOCATIONS: tuple[tuple[ValidationViewName, int, int], ...] = (
    ("25/0", 25, 0),
    ("20/5", 20, 5),
)


@dataclass(frozen=True)
class SourceSignals:
    baseline_candidates: int
    target_mod_candidates: int
    source_intersection: int
    source_intersection_rate: float
    target_mod_recurring: int
    target_mod_seeds: tuple[ModSeedDiagnostic, ...]
    target_primary_mod_share: float
    target_pp: NumericPreferenceSummary | None


@dataclass(frozen=True)
class RecoveryTransition:
    target: str
    split_index: int
    beatmap_id: int
    original_position: int
    kind: Literal["newly_recovered", "lost"]
    cause: TransitionCause


@dataclass(frozen=True)
class MetricComparison:
    recovered_anywhere: Comparison
    recall_at_10: Comparison
    recall_at_30: Comparison
    recall_at_50: Comparison
    recall_at_100: Comparison


@dataclass(frozen=True)
class HybridValidationResult:
    target_username: str
    split_index: int
    target_primary_mods: tuple[str, ...]
    source_signals: SourceSignals
    baseline: AllocationViewResult
    hybrid: AllocationViewResult
    comparison: MetricComparison
    transitions: tuple[RecoveryTransition, ...]
    baseline_leaderboard_requests: int
    target_mod_leaderboard_requests: int
    logical_hydration_requests: int
    actual_hydration_requests: int


@dataclass(frozen=True)
class SignalObservation:
    label: Comparison
    source_intersection: float
    source_intersection_rate: float
    target_mod_recurring: float
    target_mod_candidates: float
    target_primary_mod_share: float
    hydrated_compatibility_gain: float
    top10_compatibility_gain: float
    top10_overlap_difference: float


@dataclass(frozen=True)
class SignalSummary:
    label: Comparison
    count: int
    means: tuple[float, ...]
    medians: tuple[float, ...]


def compare_number(hybrid: float, baseline: float) -> Comparison:
    if hybrid > baseline:
        return "improved"
    if hybrid < baseline:
        return "worsened"
    return "tied"


def compare_views(
    baseline: HoldoutRecoveryExperimentResult,
    hybrid: HoldoutRecoveryExperimentResult,
) -> MetricComparison:
    left = baseline.preference_aware_summary
    right = hybrid.preference_aware_summary
    return MetricComparison(
        compare_number(right.recovered_anywhere, left.recovered_anywhere),
        compare_number(right.recall_at_10, left.recall_at_10),
        compare_number(right.recall_at_30, left.recall_at_30),
        compare_number(right.recall_at_50, left.recall_at_50),
        compare_number(right.recall_at_100, left.recall_at_100),
    )


def recovery_id_sets(
    baseline: Sequence[HeldOutMapRecovery],
    hybrid: Sequence[HeldOutMapRecovery],
) -> tuple[set[int], set[int], set[int]]:
    """Return newly recovered, lost, and shared recovered beatmap IDs."""
    baseline_ids = {
        item.play.beatmap_id for item in baseline
        if item.preference_aware_rank is not None
    }
    hybrid_ids = {
        item.play.beatmap_id for item in hybrid
        if item.preference_aware_rank is not None
    }
    return hybrid_ids - baseline_ids, baseline_ids - hybrid_ids, baseline_ids & hybrid_ids


def recovery_transitions(
    target: str,
    split_index: int,
    baseline: HoldoutRecoveryExperimentResult,
    hybrid: HoldoutRecoveryExperimentResult,
    hybrid_features: Sequence[CompatibilityFeatures],
    hybrid_allocated: Sequence[AllocatedCandidate],
) -> tuple[RecoveryTransition, ...]:
    baseline_by_id = {item.play.beatmap_id: item for item in baseline.held_out_maps}
    hybrid_by_id = {item.play.beatmap_id: item for item in hybrid.held_out_maps}
    hybrid_diagnostics = {
        item.play.beatmap_id: item for item in hybrid.acquisition_diagnostics
    }
    allocated = {item.candidate.user_id: item for item in hybrid_allocated}
    feature_rank = {item.user_id: rank for rank, item in enumerate(hybrid_features, 1)}
    transitions: list[RecoveryTransition] = []
    for beatmap_id in sorted(baseline_by_id.keys() | hybrid_by_id.keys()):
        old = baseline_by_id[beatmap_id]
        new = hybrid_by_id[beatmap_id]
        old_recovered = old.preference_aware_rank is not None
        new_recovered = new.preference_aware_rank is not None
        if old_recovered == new_recovered:
            continue
        cause: TransitionCause = "unknown_or_mixed"
        if new_recovered:
            diagnostic = hybrid_diagnostics.get(beatmap_id)
            supporter_ids = set(
                diagnostic.selected_supporter_user_ids if diagnostic else ()
            )
            target_mod_ranks = [
                feature_rank[user_id]
                for user_id, item in allocated.items()
                if item.allocation_source == "target_mod"
                and user_id in feature_rank
                and user_id in supporter_ids
            ]
            if any(rank <= 10 for rank in target_mod_ranks):
                cause = "target_mod_top_10"
            elif any(rank <= 15 for rank in target_mod_ranks):
                cause = "target_mod_ranks_11_15"
            elif supporter_ids:
                cause = "changed_baseline_membership"
        transitions.append(RecoveryTransition(
            target,
            split_index,
            beatmap_id,
            new.play.position,
            "newly_recovered" if new_recovered else "lost",
            cause,
        ))
    return tuple(transitions)


def summarize_signal_groups(
    observations: Sequence[SignalObservation],
) -> tuple[SignalSummary, ...]:
    fields = (
        "source_intersection", "source_intersection_rate", "target_mod_recurring",
        "target_mod_candidates", "target_primary_mod_share",
        "hydrated_compatibility_gain", "top10_compatibility_gain",
        "top10_overlap_difference",
    )
    summaries: list[SignalSummary] = []
    for label in ("improved", "worsened", "tied"):
        group = [item for item in observations if item.label == label]
        if not group:
            summaries.append(SignalSummary(label, 0, (), ()))
            continue
        columns = [[float(getattr(item, field)) for item in group] for field in fields]
        summaries.append(SignalSummary(
            label, len(group), tuple(fmean(column) for column in columns),
            tuple(float(median(column)) for column in columns),
        ))
    return tuple(summaries)


async def evaluate_hybrid_validation(
    username: str,
    *,
    split_index: int,
    split_count: int = 8,
    osu_client: OsuApiClient | None = None,
) -> HybridValidationResult:
    if split_index < 0 or split_index >= split_count:
        raise ValueError("Split index must be within the configured split count.")
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    target, plays = _load_target_evidence(username.strip(), 100, get_session_factory())
    split = split_target_evidence(plays, 10, split_count, split_index)
    seeds = select_evenly_spaced_seeds(
        tuple(TargetMapSeed(play.position, play.beatmap_id) for play in split.training), 5
    )
    primary = _primary_mods(split.training)
    baseline_pool = await acquire_target_map_candidate_pool(
        target.user_id, target.username, seeds, client
    )
    target_mod_pool, mod_seeds = await acquire_mod_filtered_pool(
        target.user_id, target.username, seeds, primary, client
    )
    baseline_priority = source_priority(baseline_pool)
    target_mod_priority = source_priority(target_mod_pool)
    cache = HydrationCacheClient(client)
    target_pp = calculate_numeric_summary(play.performance_points for play in split.training)
    views: list[AllocationViewResult] = []
    for name, baseline_slots, target_mod_slots in VALIDATION_ALLOCATIONS:
        allocated, accounting = allocate_candidates(
            baseline_priority, target_mod_priority, baseline_slots, target_mod_slots
        )
        marker = tuple(seed.beatmap_id for seed in seeds[:2])
        candidates = tuple(
            TargetMapCandidate(item.candidate.user_id, item.candidate.username, marker)
            for item in allocated
        )
        pool = TargetMapCandidatePool(
            target.user_id, target.username, seeds, candidates,
            ((len(marker), len(candidates)),) if candidates else (), 0,
        )

        async def supplied_pool(
            _id: int, _name: str, _seeds: Sequence[TargetMapSeed], _client: object,
            *, value: TargetMapCandidatePool = pool,
        ) -> TargetMapCandidatePool:
            return value

        recovery = await evaluate_holdout_recovery(
            username, top_plays=100, holdout_count=10, split_count=split_count,
            split_index=split_index, seed_count=5, hydration_budget=25,
            candidate_top_plays=100, similar_player_limit=15,
            osu_client=cache, acquisition_function=supplied_pool,
        )
        ranking = recovery.ranking_result
        assert ranking is not None
        features = tuple(
            _features(rank, player, primary, target_pp)
            for rank, player in enumerate(ranking.candidates, 1)
        )
        by_id = {item.candidate.user_id: item for item in allocated}
        overlaps = [item.independent_overlap for item in features]
        views.append(AllocationViewResult(
            name, accounting, recovery, features,
            HydratedDiagnostics(
                fmean(overlaps) if overlaps else 0.0,
                float(median(overlaps)) if overlaps else 0.0,
                sum(value == 0 for value in overlaps),
                sum(value >= 1 for value in overlaps),
                sum(value >= 2 for value in overlaps),
                sum(value >= 5 for value in overlaps),
                sum(item.target_primary_mod_share > 0 for item in features),
                sum(item.target_primary_mod_share >= .25 for item in features),
                sum(item.target_primary_mod_share >= .5 for item in features),
                sum(item.pp_iqr_overlaps is True for item in features),
                sum(item.target_primary_mod_share >= .5 and item.pp_iqr_overlaps is True for item in features),
            ),
            _selection_summary(features[:10]), _selection_summary(features[:15]),
            _retention(features[:10], by_id), _retention(features[:15], by_id),
            _placement(features, by_id), allocated,
        ))
    baseline, hybrid = views
    baseline_ids = {item.user_id for item in baseline_pool.candidates}
    mod_ids = {item.user_id for item in target_mod_pool.candidates}
    intersection = len(baseline_ids & mod_ids)
    union = len(baseline_ids | mod_ids)
    primary_share = (
        sum(play.mods == primary for play in split.training) / len(split.training)
        if split.training else 0.0
    )
    signals = SourceSignals(
        len(baseline_ids), len(mod_ids), intersection,
        intersection / union if union else 0.0,
        sum(item.seed_hit_count >= 2 for item in target_mod_pool.candidates),
        mod_seeds, primary_share, target_pp,
    )
    return HybridValidationResult(
        target.username, split_index, primary, signals, baseline, hybrid,
        compare_views(baseline.recovery, hybrid.recovery),
        recovery_transitions(
            target.username, split_index, baseline.recovery,
            hybrid.recovery, hybrid.features, hybrid.allocated,
        ),
        baseline_pool.leaderboard_requests_made,
        target_mod_pool.leaderboard_requests_made,
        50,
        cache.actual_top_play_requests,
    )

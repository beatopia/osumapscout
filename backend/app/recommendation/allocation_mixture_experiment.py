"""Offline T0053 budget-neutral baseline/target-mod allocation experiment."""

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
from backend.app.recommendation.candidate_acquisition_experiment import (
    HydratedDiagnostics,
    HydrationCacheClient,
    acquire_mod_filtered_pool,
)
from backend.app.recommendation.holdout_recovery import (
    HoldoutRecoveryExperimentResult,
    _load_target_evidence,
    evaluate_holdout_recovery,
    split_target_evidence,
)
from backend.app.recommendation.player_compatibility_experiment import (
    CompatibilityFeatures,
    SelectionSummary,
    _features,
    _primary_mods,
    _selection_summary,
)
from backend.app.recommendation.preference_evidence import calculate_numeric_summary
from backend.app.similarity.ranked_candidates import select_candidates_with_budget

AllocationName = Literal["25/0", "20/5", "15/10", "10/15"]
ALLOCATIONS: tuple[tuple[AllocationName, int, int], ...] = (
    ("25/0", 25, 0),
    ("20/5", 20, 5),
    ("15/10", 15, 10),
    ("10/15", 10, 15),
)


@dataclass(frozen=True)
class AllocatedCandidate:
    candidate: TargetMapCandidate
    allocation_source: Literal["baseline", "target_mod", "baseline_backfill"]
    present_in_target_mod_source: bool


@dataclass(frozen=True)
class AllocationAccounting:
    requested_baseline: int
    requested_target_mod: int
    baseline_only: int
    target_mod_only: int
    present_in_both_pools: int
    duplicates_skipped: int
    baseline_backfill: int
    final_unique: int


@dataclass(frozen=True)
class SourceRetention:
    baseline_phase: int
    target_mod_phase: int
    baseline_backfill: int
    present_in_both_pools: int


@dataclass(frozen=True)
class TargetModPlacement:
    ranks_1_10: int
    ranks_11_15: int
    below_15: int


@dataclass(frozen=True)
class AllocationViewResult:
    name: AllocationName
    accounting: AllocationAccounting
    recovery: HoldoutRecoveryExperimentResult
    features: tuple[CompatibilityFeatures, ...]
    hydrated: HydratedDiagnostics
    top10: SelectionSummary
    top15: SelectionSummary
    top10_sources: SourceRetention
    top15_sources: SourceRetention
    target_mod_placement: TargetModPlacement
    allocated: tuple[AllocatedCandidate, ...]


@dataclass(frozen=True)
class AllocationMixtureResult:
    target_username: str
    split_index: int
    target_primary_mods: tuple[str, ...]
    views: tuple[AllocationViewResult, ...]
    baseline_leaderboard_requests: int
    target_mod_leaderboard_requests: int
    logical_hydration_requests: int
    actual_hydration_requests: int


def source_priority(
    pool: TargetMapCandidatePool,
    limit: int = 50,
) -> tuple[TargetMapCandidate, ...]:
    """Reuse the existing recurring-first/stratified-one-hit priority."""
    selection = select_candidates_with_budget(
        pool.candidates, pool.selected_seeds, min(limit, 50)
    )
    return tuple(item.candidate for item in selection.ordered)


def allocate_candidates(
    baseline: Sequence[TargetMapCandidate],
    target_mod: Sequence[TargetMapCandidate],
    baseline_slots: int,
    target_mod_slots: int,
) -> tuple[tuple[AllocatedCandidate, ...], AllocationAccounting]:
    """Construct one deterministic allocation with baseline-only backfill."""
    if baseline_slots < 0 or target_mod_slots < 0 or baseline_slots + target_mod_slots != 25:
        raise ValueError("Allocation slots must be non-negative and total 25.")
    baseline_ids = {item.user_id for item in baseline}
    target_mod_ids = {item.user_id for item in target_mod}
    selected: list[AllocatedCandidate] = []
    selected_ids: set[int] = set()
    for candidate in baseline:
        if candidate.user_id in selected_ids:
            continue
        selected.append(AllocatedCandidate(
            candidate, "baseline", candidate.user_id in target_mod_ids
        ))
        selected_ids.add(candidate.user_id)
        if len(selected) == baseline_slots:
            break
    duplicates = 0
    target_added = 0
    for candidate in target_mod:
        if target_added == target_mod_slots:
            break
        if candidate.user_id in selected_ids:
            duplicates += 1
            continue
        selected.append(AllocatedCandidate(candidate, "target_mod", True))
        selected_ids.add(candidate.user_id)
        target_added += 1
    backfill = 0
    for candidate in baseline:
        if len(selected) == 25:
            break
        if candidate.user_id in selected_ids:
            continue
        selected.append(AllocatedCandidate(
            candidate, "baseline_backfill", candidate.user_id in target_mod_ids
        ))
        selected_ids.add(candidate.user_id)
        backfill += 1
    both = sum(item.candidate.user_id in baseline_ids & target_mod_ids for item in selected)
    return tuple(selected), AllocationAccounting(
        baseline_slots,
        target_mod_slots,
        sum(item.allocation_source != "target_mod" and not item.present_in_target_mod_source for item in selected),
        sum(item.allocation_source == "target_mod" and item.candidate.user_id not in baseline_ids for item in selected),
        both,
        duplicates,
        backfill,
        len(selected),
    )


async def evaluate_allocation_mixtures(
    username: str,
    *,
    split_index: int,
    split_count: int = 3,
    osu_client: OsuApiClient | None = None,
) -> AllocationMixtureResult:
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
    target_mod_pool, _ = await acquire_mod_filtered_pool(
        target.user_id, target.username, seeds, primary, client
    )
    baseline_priority = source_priority(baseline_pool)
    target_mod_priority = source_priority(target_mod_pool)
    cache = HydrationCacheClient(client)
    target_pp = calculate_numeric_summary(play.performance_points for play in split.training)
    views: list[AllocationViewResult] = []
    for name, baseline_slots, target_mod_slots in ALLOCATIONS:
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
            name,
            accounting,
            recovery,
            features,
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
            _selection_summary(features[:10]),
            _selection_summary(features[:15]),
            _retention(features[:10], by_id),
            _retention(features[:15], by_id),
            _placement(features, by_id),
            allocated,
        ))
    return AllocationMixtureResult(
        target.username,
        split_index,
        primary,
        tuple(views),
        baseline_pool.leaderboard_requests_made,
        target_mod_pool.leaderboard_requests_made,
        25 * len(ALLOCATIONS),
        cache.actual_top_play_requests,
    )


def _retention(
    features: Sequence[CompatibilityFeatures],
    by_id: dict[int, AllocatedCandidate],
) -> SourceRetention:
    items = [by_id[item.user_id] for item in features]
    return SourceRetention(
        sum(item.allocation_source == "baseline" for item in items),
        sum(item.allocation_source == "target_mod" for item in items),
        sum(item.allocation_source == "baseline_backfill" for item in items),
        sum(item.present_in_target_mod_source for item in items),
    )


def _placement(
    features: Sequence[CompatibilityFeatures],
    by_id: dict[int, AllocatedCandidate],
) -> TargetModPlacement:
    ranks = [
        rank for rank, item in enumerate(features, 1)
        if by_id[item.user_id].allocation_source == "target_mod"
    ]
    return TargetModPlacement(
        sum(rank <= 10 for rank in ranks),
        sum(11 <= rank <= 15 for rank in ranks),
        sum(rank > 15 for rank in ranks),
    )

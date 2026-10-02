"""Offline T0050 candidate-user acquisition experiment."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Literal

from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapCandidatePool,
    TargetMapSeed,
    acquire_target_map_candidate_pool,
)
from backend.app.database.connection import get_session_factory
from backend.app.osu.client import OsuApiClient, OsuCredentials, OsuRankingUser, OsuTopPlay
from backend.app.recommendation.holdout_recovery import (
    HoldoutRecoveryExperimentResult,
    TargetPlayEvidence,
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

AcquisitionName = Literal["baseline", "target_mod", "performance", "mixed"]
VIEW_NAMES: tuple[AcquisitionName, ...] = ("baseline", "target_mod", "performance", "mixed")
RANKING_PAGE_SIZE = 50
RANKING_PAGE_RADIUS = 1
MAX_RANKING_REQUESTS = 3
MAX_RANKING_PAGE = 200
HYDRATION_LIMIT = 25


@dataclass(frozen=True)
class ModSeedDiagnostic:
    beatmap_id: int
    mods: tuple[str, ...]
    score_rows: int
    unique_users: int


@dataclass(frozen=True)
class AcquisitionDiagnostics:
    raw_users: int
    unique_users: int
    recurring_users: int
    selected_users: int
    source_both: int = 0
    source_mod_only: int = 0
    source_performance_only: int = 0


@dataclass(frozen=True)
class HydratedDiagnostics:
    mean_overlap: float
    median_overlap: float
    overlap_zero: int
    overlap_ge1: int
    overlap_ge2: int
    overlap_ge5: int
    mod_positive: int
    mod_ge25: int
    mod_ge50: int
    pp_overlap: int
    both: int


@dataclass(frozen=True)
class AcquisitionViewResult:
    name: AcquisitionName
    recovery: HoldoutRecoveryExperimentResult
    acquisition: AcquisitionDiagnostics
    hydrated: HydratedDiagnostics
    top10: SelectionSummary
    top15: SelectionSummary
    features: tuple[CompatibilityFeatures, ...]
    sources: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class CandidateAcquisitionResult:
    target_username: str
    split_index: int
    target_primary_mods: tuple[str, ...]
    target_global_rank: int | None
    target_profile_pp: float | None
    ranking_pages: tuple[int, ...]
    ranking_candidate_rank_range: tuple[int, int] | None
    ranking_candidate_pp_range: tuple[float, float] | None
    mod_seeds: tuple[ModSeedDiagnostic, ...]
    views: tuple[AcquisitionViewResult, ...]
    logical_leaderboard_requests: int
    logical_ranking_requests: int
    logical_top_play_requests: int
    actual_top_play_requests: int


class HydrationCacheClient:
    """Share candidate top-play responses across experimental views in one run."""

    def __init__(self, client: OsuApiClient) -> None:
        self.client = client
        self.cache: dict[tuple[int, int], tuple[OsuTopPlay, ...]] = {}
        self.actual_top_play_requests = 0

    async def get_top_plays_by_user_id(self, user_id: int, limit: int = 100) -> list[OsuTopPlay]:
        key = (user_id, limit)
        if key not in self.cache:
            self.cache[key] = tuple(await self.client.get_top_plays_by_user_id(user_id, limit))
            self.actual_top_play_requests += 1
        return list(self.cache[key])


def performance_neighborhood_pages(global_rank: int) -> tuple[int, ...]:
    """Return at most three direct pages centered on the target's expected page."""
    if isinstance(global_rank, bool) or not isinstance(global_rank, int) or global_rank < 1:
        raise ValueError("Global rank must be a positive integer.")
    center = min((global_rank - 1) // RANKING_PAGE_SIZE + 1, MAX_RANKING_PAGE)
    return tuple(range(
        max(1, center - RANKING_PAGE_RADIUS),
        min(MAX_RANKING_PAGE, center + RANKING_PAGE_RADIUS) + 1,
    ))


async def acquire_mod_filtered_pool(
    target_user_id: int, target_username: str, seeds: Sequence[TargetMapSeed],
    mods: tuple[str, ...], client: OsuApiClient,
) -> tuple[TargetMapCandidatePool, tuple[ModSeedDiagnostic, ...]]:
    occurrences: dict[int, list[int]] = {}
    names: dict[int, str | None] = {}
    order: dict[int, int] = {}
    diagnostics: list[ModSeedDiagnostic] = []
    raw = 0
    for seed in seeds:
        rows = await client.get_beatmap_leaderboard_users(seed.beatmap_id, mods=mods)
        raw += len(rows)
        seen: set[int] = set()
        for user in rows:
            if user.user_id == target_user_id or user.user_id in seen:
                continue
            seen.add(user.user_id)
            if user.user_id not in occurrences:
                order[user.user_id] = len(order)
                occurrences[user.user_id] = []
                names[user.user_id] = user.username
            occurrences[user.user_id].append(seed.beatmap_id)
        diagnostics.append(ModSeedDiagnostic(seed.beatmap_id, mods, len(rows), len(seen)))
    candidates = tuple(TargetMapCandidate(user_id, names[user_id], tuple(seed_ids)) for user_id, seed_ids in sorted(
        occurrences.items(), key=lambda item: (-len(item[1]), order[item[0]], item[0])
    ))
    distribution = Counter(item.seed_hit_count for item in candidates)
    return TargetMapCandidatePool(
        target_user_id, target_username, tuple(seeds), candidates,
        tuple(sorted(distribution.items(), reverse=True)), len(seeds)
    ), tuple(diagnostics)


async def acquire_performance_pool(
    target_user_id: int, target_username: str, target_rank: int,
    seeds: Sequence[TargetMapSeed], client: OsuApiClient,
) -> tuple[TargetMapCandidatePool, tuple[OsuRankingUser, ...], tuple[int, ...]]:
    pages = performance_neighborhood_pages(target_rank)
    users: dict[int, OsuRankingUser] = {}
    for page in pages:
        result = await client.get_osu_performance_ranking((("page", str(page)),))
        for user in result.users:
            if user.user_id != target_user_id:
                users.setdefault(user.user_id, user)
    ordered = tuple(sorted(users.values(), key=lambda item: (
        abs((item.global_rank if item.global_rank is not None else 10**12) - target_rank),
        item.global_rank if item.global_rank is not None else 10**12,
        item.user_id,
    )))
    marker = tuple(seed.beatmap_id for seed in seeds[:2])
    candidates = tuple(TargetMapCandidate(item.user_id, item.username, marker) for item in ordered)
    return TargetMapCandidatePool(
        target_user_id, target_username, tuple(seeds), candidates,
        ((len(marker), len(candidates)),) if candidates else (), len(pages)
    ), ordered, pages


def build_mixed_pool(
    target_user_id: int, target_username: str, seeds: Sequence[TargetMapSeed],
    mod_pool: TargetMapCandidatePool, performance_pool: TargetMapCandidatePool,
) -> tuple[TargetMapCandidatePool, dict[int, str]]:
    mod = {item.user_id: item for item in mod_pool.candidates}
    perf = {item.user_id: item for item in performance_pool.candidates}
    recurring = {item.user_id for item in mod_pool.candidates if item.seed_hit_count >= 2}
    ordered_ids = (
        [item.user_id for item in mod_pool.candidates if item.user_id in perf]
        + [item.user_id for item in mod_pool.candidates if item.user_id not in perf and item.user_id in recurring]
        + [item.user_id for item in mod_pool.candidates if item.user_id not in perf and item.user_id not in recurring]
        + [item.user_id for item in performance_pool.candidates if item.user_id not in mod]
    )
    marker = tuple(seed.beatmap_id for seed in seeds[:2])
    candidates = tuple(TargetMapCandidate(
        user_id, (mod.get(user_id) or perf[user_id]).username, marker
    ) for user_id in dict.fromkeys(ordered_ids))
    sources = {user_id: ("both" if user_id in mod and user_id in perf else "target_mod" if user_id in mod else "performance") for user_id in ordered_ids}
    return TargetMapCandidatePool(
        target_user_id, target_username, tuple(seeds), candidates,
        ((len(marker), len(candidates)),) if candidates else (), 0
    ), sources


async def evaluate_candidate_acquisition(
    username: str, *, split_index: int, split_count: int = 3,
    osu_client: OsuApiClient | None = None,
) -> CandidateAcquisitionResult:
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    target, plays = _load_target_evidence(username.strip(), 100, get_session_factory())
    split = split_target_evidence(plays, 10, split_count, split_index)
    seeds = tuple(TargetMapSeed(play.position, play.beatmap_id) for play in split.training)
    from backend.app.candidates.target_maps import select_evenly_spaced_seeds
    seeds = select_evenly_spaced_seeds(seeds, 5)
    primary = _primary_mods(split.training)
    profile = await client.get_user_by_username(target.username)
    if profile.global_rank is None:
        raise ValueError("Performance-neighborhood acquisition requires a target global rank.")
    baseline = await acquire_target_map_candidate_pool(target.user_id, target.username, seeds, client)
    mod_pool, mod_diagnostics = await acquire_mod_filtered_pool(target.user_id, target.username, seeds, primary, client)
    perf_pool, ranking_users, pages = await acquire_performance_pool(target.user_id, target.username, profile.global_rank, seeds, client)
    mixed_pool, mixed_sources = build_mixed_pool(target.user_id, target.username, seeds, mod_pool, perf_pool)
    pools = {"baseline": baseline, "target_mod": mod_pool, "performance": perf_pool, "mixed": mixed_pool}
    cache = HydrationCacheClient(client)
    target_pp = calculate_numeric_summary(play.performance_points for play in split.training)
    results: list[AcquisitionViewResult] = []
    for name in VIEW_NAMES:
        pool = pools[name]
        async def supplied_pool(_id: int, _name: str, _seeds: Sequence[TargetMapSeed], _client: object, *, value: TargetMapCandidatePool = pool) -> TargetMapCandidatePool:
            return value
        recovery = await evaluate_holdout_recovery(
            username, top_plays=100, holdout_count=10, split_count=split_count,
            split_index=split_index, seed_count=5, hydration_budget=HYDRATION_LIMIT,
            candidate_top_plays=100, similar_player_limit=15,
            osu_client=cache, acquisition_function=supplied_pool,
        )
        ranking = recovery.ranking_result
        assert ranking is not None
        features = tuple(_features(rank, player, primary, target_pp) for rank, player in enumerate(ranking.candidates, 1))
        overlaps = [item.independent_overlap for item in features]
        selected_ids = {item.user_id for item in features}
        if name == "mixed":
            source_map = mixed_sources
        elif name == "target_mod":
            source_map = {item.user_id: "target_mod" for item in pool.candidates}
        elif name == "performance":
            source_map = {item.user_id: "performance" for item in pool.candidates}
        else:
            source_map = {item.user_id: "baseline" for item in pool.candidates}
        raw = sum(item.score_rows for item in mod_diagnostics) if name == "target_mod" else len(pool.candidates)
        results.append(AcquisitionViewResult(
            name, recovery,
            AcquisitionDiagnostics(
                raw, len(pool.candidates), sum(item.seed_hit_count >= 2 for item in pool.candidates),
                len(features),
                sum(source_map.get(user_id) == "both" for user_id in selected_ids),
                sum(source_map.get(user_id) == "target_mod" for user_id in selected_ids),
                sum(source_map.get(user_id) == "performance" for user_id in selected_ids),
            ),
            HydratedDiagnostics(
                fmean(overlaps) if overlaps else 0.0, float(median(overlaps)) if overlaps else 0.0,
                sum(x == 0 for x in overlaps), sum(x >= 1 for x in overlaps),
                sum(x >= 2 for x in overlaps), sum(x >= 5 for x in overlaps),
                sum(x.target_primary_mod_share > 0 for x in features),
                sum(x.target_primary_mod_share >= .25 for x in features),
                sum(x.target_primary_mod_share >= .5 for x in features),
                sum(x.pp_iqr_overlaps is True for x in features),
                sum(x.target_primary_mod_share >= .5 and x.pp_iqr_overlaps is True for x in features),
            ),
            _selection_summary(features[:10]), _selection_summary(features[:15]),
            features, tuple((item.user_id, source_map.get(item.user_id, name)) for item in features),
        ))
    ranks = [item.global_rank for item in ranking_users if item.global_rank is not None]
    pps = [item.performance_points for item in ranking_users if item.performance_points is not None]
    return CandidateAcquisitionResult(
        target.username, split_index, primary, profile.global_rank, profile.performance_points,
        pages, (min(ranks), max(ranks)) if ranks else None,
        (min(pps), max(pps)) if pps else None, mod_diagnostics, tuple(results),
        len(seeds) * 2, len(pages), HYDRATION_LIMIT * len(VIEW_NAMES),
        cache.actual_top_play_requests,
    )

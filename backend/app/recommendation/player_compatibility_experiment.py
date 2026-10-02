"""Offline T0049 player-compatibility selection experiment."""

from collections import Counter
from dataclasses import dataclass, replace
from statistics import fmean, median
from typing import Literal

from backend.app.osu.client import OsuApiClient, OsuCredentials, OsuTopPlay
from backend.app.recommendation.holdout_recovery import (
    HoldoutRecoveryExperimentResult,
    OrderingRecoverySummary,
    TargetPlayEvidence,
    evaluate_holdout_recovery,
    summarize_recovery,
)
from backend.app.recommendation.preference_evidence import (
    NumericPreferenceSummary,
    calculate_numeric_summary,
)
from backend.app.recommendation.service import build_hybrid_ranking
from backend.app.similarity.ranked_candidates import RankedSimilarPlayer

ViewName = Literal["baseline", "mod_first", "pp_first", "compatibility_first"]
VIEW_NAMES: tuple[ViewName, ...] = (
    "baseline", "mod_first", "pp_first", "compatibility_first"
)


@dataclass(frozen=True)
class CompatibilityFeatures:
    baseline_rank: int
    user_id: int
    username: str | None
    independent_overlap: int
    dominant_mods: tuple[str, ...]
    target_primary_mod_share: float
    pp: NumericPreferenceSummary | None
    pp_iqr_overlaps: bool | None
    median_pp_distance: float | None


@dataclass(frozen=True)
class SelectionSummary:
    count: int
    mean_mod_share: float
    median_mod_share: float
    mod_share_at_least_half: int
    pp_iqr_overlap: int
    mean_median_pp_distance: float | None
    median_median_pp_distance: float | None
    mean_independent_overlap: float
    median_independent_overlap: float
    minimum_independent_overlap: int


@dataclass(frozen=True)
class CompatibilityViewResult:
    name: ViewName
    ordered_players: tuple[CompatibilityFeatures, ...]
    top10: SelectionSummary
    top15: SelectionSummary
    candidate_map_count: int
    recovery: OrderingRecoverySummary


@dataclass(frozen=True)
class PlayerCompatibilityResult:
    target_username: str
    split_index: int
    target_primary_mods: tuple[str, ...]
    target_pp: NumericPreferenceSummary | None
    hydrated_pool: tuple[CompatibilityFeatures, ...]
    views: tuple[CompatibilityViewResult, ...]
    leaderboard_requests: int
    top_play_requests: int


async def evaluate_player_compatibility(
    username: str,
    *,
    split_index: int,
    split_count: int = 3,
    osu_client: OsuApiClient | None = None,
) -> PlayerCompatibilityResult:
    """Hydrate once, then derive four in-memory player-selection views."""
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    recovery = await evaluate_holdout_recovery(
        username,
        top_plays=100,
        holdout_count=10,
        split_count=split_count,
        split_index=split_index,
        seed_count=5,
        hydration_budget=25,
        candidate_top_plays=100,
        similar_player_limit=15,
        osu_client=client,
    )
    return analyze_player_compatibility(recovery)


def analyze_player_compatibility(
    recovery: HoldoutRecoveryExperimentResult,
) -> PlayerCompatibilityResult:
    ranking = recovery.ranking_result
    profile = recovery.target_preference_profile
    if ranking is None or profile is None or not recovery.training_plays:
        raise ValueError("Holdout result lacks reusable training/ranking evidence.")
    primary = _primary_mods(recovery.training_plays)
    target_pp = calculate_numeric_summary(
        play.performance_points for play in recovery.training_plays
    )
    pool = tuple(
        _features(rank, player, primary, target_pp)
        for rank, player in enumerate(ranking.candidates, 1)
    )
    by_id = {item.user_id: item for item in pool}
    held_ids = tuple(item.play.beatmap_id for item in recovery.held_out_maps)
    views: list[CompatibilityViewResult] = []
    for name in VIEW_NAMES:
        ordered = _order(pool, name)
        ordered_players = tuple(
            ranking.candidates[item.baseline_rank - 1] for item in ordered
        )
        view_ranking = replace(ranking, candidates=ordered_players)
        maps = build_hybrid_ranking(view_ranking, profile)
        ids = tuple(
            item.preference_evidence.collaborative.candidate_map.beatmap_id
            for item in maps
        )
        views.append(CompatibilityViewResult(
            name=name,
            ordered_players=tuple(by_id[item.user_id] for item in ordered),
            top10=_selection_summary(ordered[:10]),
            top15=_selection_summary(ordered[:15]),
            candidate_map_count=len(ids),
            recovery=summarize_recovery(held_ids, ids),
        ))
    expected = {item.user_id for item in pool}
    if any({item.user_id for item in view.ordered_players} != expected for view in views):
        raise ValueError("Compatibility views do not contain the same hydrated users.")
    return PlayerCompatibilityResult(
        target_username=recovery.target_username,
        split_index=recovery.split_index,
        target_primary_mods=primary,
        target_pp=target_pp,
        hydrated_pool=pool,
        views=tuple(views),
        leaderboard_requests=recovery.leaderboard_requests_made,
        top_play_requests=recovery.top_play_requests_made,
    )


def _primary_mods(plays: tuple[TargetPlayEvidence, ...]) -> tuple[str, ...]:
    counts = Counter(play.mods for play in plays)
    return min(counts, key=lambda mods: (-counts[mods], mods)) if counts else ()


def _features(
    rank: int,
    player: RankedSimilarPlayer,
    primary: tuple[str, ...],
    target_pp: NumericPreferenceSummary | None,
) -> CompatibilityFeatures:
    counts = Counter(play.mods for play in player.hydrated_top_plays)
    total = len(player.hydrated_top_plays)
    dominant = min(counts, key=lambda mods: (-counts[mods], mods)) if counts else ()
    pp = calculate_numeric_summary(play.performance_points for play in player.hydrated_top_plays)
    comparable = pp is not None and target_pp is not None
    return CompatibilityFeatures(
        baseline_rank=rank,
        user_id=player.user_id,
        username=player.username,
        independent_overlap=player.seed_excluded_shared_beatmap_count,
        dominant_mods=dominant,
        target_primary_mod_share=counts[primary] / total if total else 0.0,
        pp=pp,
        pp_iqr_overlaps=(
            pp.first_quartile <= target_pp.third_quartile
            and pp.third_quartile >= target_pp.first_quartile
            if comparable else None
        ),
        median_pp_distance=(abs(pp.median - target_pp.median) if comparable else None),
    )


def _order(
    pool: tuple[CompatibilityFeatures, ...], name: ViewName
) -> tuple[CompatibilityFeatures, ...]:
    if name == "baseline":
        return pool
    if name == "mod_first":
        return tuple(sorted(pool, key=lambda item: (-item.target_primary_mod_share, item.baseline_rank)))
    if name == "pp_first":
        return tuple(sorted(pool, key=lambda item: (
            item.pp_iqr_overlaps is None,
            -(item.pp_iqr_overlaps is True),
            item.median_pp_distance if item.median_pp_distance is not None else 0.0,
            item.baseline_rank,
        )))
    return tuple(sorted(pool, key=lambda item: (
        item.pp_iqr_overlaps is None,
        -(item.pp_iqr_overlaps is True),
        -item.target_primary_mod_share,
        item.median_pp_distance if item.median_pp_distance is not None else 0.0,
        item.baseline_rank,
    )))


def _selection_summary(items: tuple[CompatibilityFeatures, ...]) -> SelectionSummary:
    shares = [item.target_primary_mod_share for item in items]
    distances = [item.median_pp_distance for item in items if item.median_pp_distance is not None]
    overlaps = [item.independent_overlap for item in items]
    return SelectionSummary(
        count=len(items),
        mean_mod_share=fmean(shares) if shares else 0.0,
        median_mod_share=float(median(shares)) if shares else 0.0,
        mod_share_at_least_half=sum(value >= 0.5 for value in shares),
        pp_iqr_overlap=sum(item.pp_iqr_overlaps is True for item in items),
        mean_median_pp_distance=fmean(distances) if distances else None,
        median_median_pp_distance=float(median(distances)) if distances else None,
        mean_independent_overlap=fmean(overlaps) if overlaps else 0.0,
        median_independent_overlap=float(median(overlaps)) if overlaps else 0.0,
        minimum_independent_overlap=min(overlaps, default=0),
    )

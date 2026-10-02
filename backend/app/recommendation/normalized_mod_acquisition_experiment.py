"""Acquire candidates from both variants of one HD-normalized mod family."""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapCandidatePool,
    TargetMapSeed,
    select_evenly_spaced_seeds,
)
from backend.app.database.connection import get_session_factory
from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.candidate_acquisition_experiment import (
    HydrationCacheClient,
    acquire_mod_filtered_pool,
)
from backend.app.recommendation.holdout_recovery import (
    OrderingRecoverySummary,
    _load_target_evidence,
    evaluate_holdout_recovery,
    split_target_evidence,
    summarize_recovery,
)
from backend.app.recommendation.effective_attributes import effective_attributes
from backend.app.recommendation.effective_preference_experiment import (
    build_effective_candidates,
    build_effective_target_profile,
)
from backend.app.recommendation.mod_family_eligibility_experiment import (
    PlayerModCompatibility,
    describe_player,
    target_style,
)
from backend.app.recommendation.preference_evidence import (
    NumericPreferenceSummary,
    calculate_numeric_summary,
)
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate
from backend.app.recommendation.preference_ranking import rank_candidate_map_preferences
from backend.app.recommendation.service import build_hybrid_ranking
from backend.app.similarity.gameplay_mods import (
    compatibility_minimum_share,
    mod_family_variants,
)


@dataclass(frozen=True)
class NormalizedModAcquisitionResult:
    target_username: str
    split_index: int
    target_normalized_mods: tuple[str, ...]
    target_normalized_share: float
    calibrated_minimum_share: float
    queried_mods: tuple[tuple[str, ...], ...]
    acquired_users: int
    hydrated_users: int
    eligible_users: int
    calibrated_eligible_users: int
    effective_range_eligible_users: int
    players: tuple[PlayerModCompatibility, ...]
    source_recovery: OrderingRecoverySummary
    eligible_recovery: OrderingRecoverySummary
    calibrated_recovery: OrderingRecoverySummary
    effective_range_recovery: OrderingRecoverySummary
    effective_map_recovery: OrderingRecoverySummary
    effective_map_eligible_recovery: OrderingRecoverySummary
    effective_map_eligible_count: int
    behavior_first_recovery: OrderingRecoverySummary
    leaderboard_requests: int
    hydration_requests: int


def hd_family_variants(normalized: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Return the exact no-HD and HD variants without rewriting other mods."""
    return mod_family_variants(normalized)


def calibrated_minimum_share(target_share: float) -> float:
    """Require a majority unless the target itself is less specialized."""
    return compatibility_minimum_share(target_share)


def iqr_overlaps(
    left: NumericPreferenceSummary | None,
    right: NumericPreferenceSummary | None,
) -> bool:
    """Return whether two measured interquartile ranges intersect."""
    return bool(
        left is not None
        and right is not None
        and left.first_quartile <= right.third_quartile
        and left.third_quartile >= right.first_quartile
    )


def effective_range_eligible(
    player: PlayerModCompatibility,
    target_ar: NumericPreferenceSummary | None,
    target_bpm: NumericPreferenceSummary | None,
) -> bool:
    """Require prior mod eligibility plus effective AR and BPM IQR overlap."""
    return (
        player.eligible
        and iqr_overlaps(player.effective_ar, target_ar)
        and iqr_overlaps(player.effective_bpm, target_bpm)
    )


def merge_mod_family_pools(
    target_user_id: int,
    target_username: str,
    seeds: Sequence[TargetMapSeed],
    pools: Sequence[TargetMapCandidatePool],
) -> TargetMapCandidatePool:
    """Union exact-mod pools while counting each seed at most once per user."""
    names: dict[int, str | None] = {}
    hits: dict[int, set[int]] = {}
    order: dict[int, int] = {}
    for pool in pools:
        for candidate in pool.candidates:
            if candidate.user_id not in hits:
                order[candidate.user_id] = len(order)
                hits[candidate.user_id] = set()
                names[candidate.user_id] = candidate.username
            hits[candidate.user_id].update(candidate.seed_beatmap_ids)
    candidates = tuple(
        TargetMapCandidate(user_id, names[user_id], tuple(sorted(seed_ids)))
        for user_id, seed_ids in sorted(
            hits.items(), key=lambda item: (-len(item[1]), order[item[0]], item[0])
        )
    )
    return TargetMapCandidatePool(
        target_user_id,
        target_username,
        tuple(seeds),
        candidates,
        (),
        sum(pool.leaderboard_requests_made for pool in pools),
    )


async def evaluate_normalized_mod_acquisition(
    username: str,
    *,
    split_index: int,
    osu_client: OsuApiClient | None = None,
) -> NormalizedModAcquisitionResult:
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    target, plays = _load_target_evidence(username.strip(), 100, get_session_factory())
    split = split_target_evidence(plays, 10, 8, split_index)
    seeds = select_evenly_spaced_seeds(
        tuple(TargetMapSeed(play.position, play.beatmap_id) for play in split.training), 5
    )
    _, normalized, target_share = target_style(split.training)
    calibrated_minimum = calibrated_minimum_share(target_share)
    target_effective = tuple(
        effective_attributes(play.approach_rate, play.bpm, play.mods)
        for play in split.training
    )
    target_ar = calculate_numeric_summary(item.effective_ar for item in target_effective)
    target_bpm = calculate_numeric_summary(item.effective_bpm for item in target_effective)
    variants = hd_family_variants(normalized)
    pools = tuple([
        await acquire_mod_filtered_pool(
            target.user_id, target.username, seeds, mods, client
        )
        for mods in variants
    ])
    pool = merge_mod_family_pools(
        target.user_id, target.username, seeds, tuple(item[0] for item in pools)
    )

    async def supplied_pool(
        _user_id: int,
        _username: str,
        _seeds: Sequence[TargetMapSeed],
        _client: object,
    ) -> TargetMapCandidatePool:
        return pool

    cache = HydrationCacheClient(client)
    recovery = await evaluate_holdout_recovery(
        username,
        top_plays=100,
        holdout_count=10,
        split_count=8,
        split_index=split_index,
        seed_count=5,
        hydration_budget=25,
        candidate_top_plays=100,
        similar_player_limit=15,
        osu_client=cache,
        acquisition_function=supplied_pool,
    )
    ranking = recovery.ranking_result
    profile = recovery.target_preference_profile
    if ranking is None or profile is None:
        raise ValueError("Holdout result lacks ranking or preference evidence.")
    players = tuple(
        describe_player(rank, player, normalized)
        for rank, player in enumerate(ranking.candidates, 1)
    )
    eligible_ids = {player.user_id for player in players if player.eligible}
    calibrated_ids = {
        player.user_id
        for rank, player in enumerate(ranking.candidates, 1)
        if describe_player(
            rank, player, normalized, minimum_share=calibrated_minimum
        ).eligible
    }
    calibrated_players = tuple(
        describe_player(rank, player, normalized, minimum_share=calibrated_minimum)
        for rank, player in enumerate(ranking.candidates, 1)
    )
    effective_range_ids = {
        player.user_id
        for player in calibrated_players
        if effective_range_eligible(player, target_ar, target_bpm)
    }
    eligible_ranking = replace(
        ranking,
        candidates=tuple(
            player for player in ranking.candidates if player.user_id in eligible_ids
        ),
    )
    calibrated_ranking = replace(
        ranking,
        candidates=tuple(
            player for player in ranking.candidates if player.user_id in calibrated_ids
        ),
    )
    effective_range_ranking = replace(
        ranking,
        candidates=tuple(
            player
            for player in ranking.candidates
            if player.user_id in effective_range_ids
        ),
    )
    held_out = tuple(item.play.beatmap_id for item in recovery.held_out_maps)
    source_maps = build_hybrid_ranking(ranking, profile)
    eligible_maps = build_hybrid_ranking(eligible_ranking, profile)
    calibrated_maps = build_hybrid_ranking(calibrated_ranking, profile)
    effective_range_maps = build_hybrid_ranking(effective_range_ranking, profile)
    effective_profile = build_effective_target_profile(profile, split.training)
    effective_map_ranking = rank_candidate_map_preferences(
        build_effective_candidates(calibrated_maps, effective_profile)
    )
    effective_map_eligible = tuple(
        item
        for item in effective_map_ranking
        if item.preference_evidence.approach_rate.within_target_iqr is True
        and item.preference_evidence.bpm.within_target_iqr is True
    )
    behavior_first = tuple(
        replace(item, preference_rank=rank)
        for rank, item in enumerate(
            sorted(
                effective_map_ranking,
                key=lambda item: (
                    -sum(
                        value.within_target_iqr is True
                        for value in (
                            item.preference_evidence.approach_rate,
                            item.preference_evidence.bpm,
                        )
                    ),
                    -item.preference_evidence.collaborative.support_count,
                    -item.preference_evidence.collaborative.total_independent_shared_count,
                    item.preference_evidence.collaborative.best_supporting_player_rank,
                    item.preference_evidence.collaborative.candidate_map.beatmap_id,
                ),
            ),
            1,
        )
    )
    return NormalizedModAcquisitionResult(
        target.username,
        split_index,
        normalized,
        target_share,
        calibrated_minimum,
        variants,
        len(pool.candidates),
        len(players),
        len(eligible_ids),
        len(calibrated_ids),
        len(effective_range_ids),
        players,
        summarize_recovery(held_out, _map_ids(source_maps)),
        summarize_recovery(held_out, _map_ids(eligible_maps)),
        summarize_recovery(held_out, _map_ids(calibrated_maps)),
        summarize_recovery(held_out, _map_ids(effective_range_maps)),
        summarize_recovery(held_out, _map_ids(effective_map_ranking)),
        summarize_recovery(held_out, _map_ids(effective_map_eligible)),
        len(effective_map_eligible),
        summarize_recovery(held_out, _map_ids(behavior_first)),
        pool.leaderboard_requests_made,
        cache.actual_top_play_requests,
    )


def _map_ids(items: Sequence[PreferenceRankedCandidate]) -> tuple[int, ...]:
    return tuple(
        item.preference_evidence.collaborative.candidate_map.beatmap_id
        for item in items
    )

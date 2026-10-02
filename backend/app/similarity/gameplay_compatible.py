"""Production similar-player selection with gameplay-mod compatibility."""

from dataclasses import replace

from sqlalchemy import func, select

from backend.app.candidates.target_maps import (
    TargetMapCandidatePool,
    TargetMapSeed,
    acquire_target_map_candidate_pool,
    merge_target_map_candidate_pools,
    select_evenly_spaced_seeds,
)
from backend.app.database.connection import get_session_factory
from backend.app.database.models import User, UserTopPlay
from backend.app.osu.client import OsuApiClient
from backend.app.similarity.gameplay_mods import (
    compatibility_minimum_share,
    dominant_mod_family,
    is_mod_family_compatible,
    mod_family_variants,
)
from backend.app.similarity.ranked_candidates import (
    RankedCandidateExperimentResult,
    evaluate_ranked_candidates,
    summarize_ranked_candidates,
)


async def evaluate_gameplay_compatible_candidates(
    username: str,
    *,
    seed_count: int = 5,
    hydration_budget: int = 25,
    top_plays: int = 100,
    osu_client: OsuApiClient,
) -> RankedCandidateExperimentResult:
    """Acquire within the target mod family, then filter before overlap selection."""
    requested_username = username.strip()
    create_session = get_session_factory()
    with create_session() as session:
        target = session.execute(
            select(User.user_id, User.username).where(
                func.lower(User.username) == requested_username.lower()
            )
        ).one()
        rows = session.execute(
            select(UserTopPlay.position, UserTopPlay.beatmap_id, UserTopPlay.mods)
            .where(UserTopPlay.user_id == target.user_id)
            .order_by(UserTopPlay.position)
            .limit(top_plays)
        ).all()
    family, target_share = dominant_mod_family(tuple(row.mods for row in rows))
    minimum_share = compatibility_minimum_share(target_share)
    seeds = select_evenly_spaced_seeds(
        tuple(TargetMapSeed(row.position, row.beatmap_id) for row in rows),
        seed_count,
    )
    pools = tuple(
        [
            await acquire_target_map_candidate_pool(
                target.user_id,
                target.username,
                seeds,
                osu_client,
                mods=mods,
            )
            for mods in mod_family_variants(family)
        ]
    )
    pool = merge_target_map_candidate_pools(
        target.user_id, target.username, seeds, pools
    )

    async def supplied_pool(
        _username: str,
        *,
        seed_count: int,
        osu_client: OsuApiClient,
    ) -> TargetMapCandidatePool:
        del seed_count, osu_client
        return pool

    result = await evaluate_ranked_candidates(
        requested_username,
        seed_count=seed_count,
        hydration_budget=hydration_budget,
        top_plays=top_plays,
        acquisition_function=supplied_pool,
        osu_client=osu_client,
    )
    compatible = tuple(
        player
        for player in result.candidates
        if is_mod_family_compatible(
            tuple(play.mods for play in player.hydrated_top_plays),
            family,
            minimum_share,
        )
    )
    return replace(
        result,
        candidates=compatible,
        summary=summarize_ranked_candidates(compatible),
    )

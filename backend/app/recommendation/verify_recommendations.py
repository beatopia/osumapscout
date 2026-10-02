"""Developer CLI for the production recommendation service."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.service import generate_recommendations


async def _run(username: str, limit: int) -> int:
    try:
        result = await generate_recommendations(username, limit=limit)
    except (ValueError, SQLAlchemyError) as error:
        print(f"Recommendation service failed: {error}", file=sys.stderr)
        return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError, CandidateHydrationError) as error:
        print(f"Upstream request failed: {error}", file=sys.stderr)
        return 1
    print(f"Target: {result.target_username} ({result.target_user_id})")
    primary = "".join(result.target_profile.primary_mods) or "NM"
    print(f"Primary target mods: {primary}")
    print("Target mod distribution:")
    for item in result.target_profile.mod_distribution:
        mods = "".join(item.mods) or "NM"
        print(f"  {mods}: {item.count} ({item.share:.2%})")
    pp = result.target_profile.performance_points
    print(
        "Target PP Q1/median/Q3: "
        + (f"{pp.first_quartile:.2f}/{pp.median:.2f}/{pp.third_quartile:.2f}" if pp else "unavailable")
    )
    print("Target actual-play adjusted star Q1/median/Q3: unavailable")
    ar = result.preferences.approach_rate
    bpm = result.preferences.bpm
    print(
        "Target effective AR Q1/median/Q3: "
        + (f"{ar.first_quartile:.2f}/{ar.median:.2f}/{ar.third_quartile:.2f}" if ar else "unavailable")
    )
    print(
        "Target effective BPM Q1/median/Q3: "
        + (f"{bpm.first_quartile:.2f}/{bpm.median:.2f}/{bpm.third_quartile:.2f}" if bpm else "unavailable")
    )
    print(f"Candidate maps before limit: {result.context.candidate_map_count}")
    for item in result.recommendations:
        identity = " - ".join(
            value for value in (item.artist, item.title, item.difficulty_name) if value
        ) or f"beatmap {item.beatmap_id}"
        print(f"{item.rank}. {identity} [{item.beatmap_id}]")
        mods = "".join(item.suggested_mods) or "NM"
        star = (
            item.adjusted_star_rating
            if item.adjusted_star_rating is not None
            else item.star_rating
        )
        print(
            f"   Suggested target mods: {mods}; base stars: {item.star_rating}; "
            f"adjusted stars: {star}; effective AR: {item.approach_rate}; "
            f"effective BPM: {item.bpm}"
        )
        print(f"   Cover: {item.cover_url}")
        print(f"   {item.why_recommended}")
        for supporter in item.supporting_players:
            supporter_mods = "".join(supporter.mods) or "NM"
            print(
                f"   Supporter #{supporter.similarity_rank}: "
                f"{supporter.username or supporter.user_id} ({supporter_mods})"
            )
    print("Similar-player diagnostic:")
    for player in result.similar_players:
        mods = "".join(player.dominant_mods) or "NM"
        normalized_mods = "".join(player.dominant_normalized_mods) or "NM"
        pp = player.performance_points
        pp_text = (
            f"{pp.first_quartile:.2f}/{pp.median:.2f}/{pp.third_quartile:.2f}"
            if pp else "unavailable"
        )
        print(
            f"  #{player.similarity_rank} {player.username or 'unknown'}: "
            f"overlap={player.independent_overlap}; dominant={mods}; "
            f"normalized={normalized_mods}; "
            f"target-mod-share={player.target_primary_mod_share:.2%}; "
            f"PP Q1/median/Q3={pp_text}"
        )
    requests = result.requests
    print(
        "Requests: "
        f"profile={requests.profile_requests} "
        f"target_top_play={requests.target_top_play_requests} "
        f"leaderboard={requests.leaderboard_requests} "
        f"candidate_top_play={requests.candidate_top_play_requests} "
        f"beatmap_attributes={requests.beatmap_attribute_requests}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate production recommendations.")
    parser.add_argument("username")
    parser.add_argument("--limit", type=int, default=20)
    arguments = parser.parse_args()
    return asyncio.run(_run(arguments.username, arguments.limit))


if __name__ == "__main__":
    raise SystemExit(main())

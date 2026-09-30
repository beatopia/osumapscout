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
    print(f"Candidate maps before limit: {result.context.candidate_map_count}")
    for item in result.recommendations:
        identity = " - ".join(
            value for value in (item.artist, item.title, item.difficulty_name) if value
        ) or f"beatmap {item.beatmap_id}"
        print(f"{item.rank}. {identity} [{item.beatmap_id}]")
        print(f"   {item.why_recommended}")
    requests = result.requests
    print(
        "Requests: "
        f"profile={requests.profile_requests} "
        f"target_top_play={requests.target_top_play_requests} "
        f"leaderboard={requests.leaderboard_requests} "
        f"candidate_top_play={requests.candidate_top_play_requests}"
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

"""Developer command for bounded candidate top-play hydration."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.discovery import CandidateTargetNotFoundError
from backend.app.candidates.hydration import (
    CandidateHydrationError,
    CandidateHydrationResult,
    hydrate_candidate_top_plays,
)
from backend.app.osu.client import (
    OsuApiError,
    OsuAuthenticationError,
    OsuNetworkError,
)


def print_result(result: CandidateHydrationResult) -> None:
    """Print concise request counts and hydrated evidence sizes."""
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Candidates discovered: {result.discovered_candidate_count}")
    print(f"Candidates hydrated: {len(result.hydrated_candidates)}")
    print(f"Ranking requests: {result.ranking_requests_made}")
    print(f"Top-play requests: {result.top_play_requests_made}")

    for position, candidate in enumerate(result.hydrated_candidates, start=1):
        username = candidate.username or "username unavailable"
        sources = ", ".join(candidate.sources)
        preview = ", ".join(
            str(play.beatmap_id) for play in candidate.top_plays[:3]
        )
        print(f"\n{position}. {username} ({candidate.user_id}) [{sources}]")
        print(f"   Top plays: {len(candidate.top_plays)}")
        if preview:
            print(f"   Beatmaps: {preview}")


async def _run(
    username: str,
    candidate_limit: int,
    hydrate_limit: int,
    top_plays: int,
) -> int:
    try:
        result = await hydrate_candidate_top_plays(
            username,
            candidate_pool_limit=candidate_limit,
            hydrate_limit=hydrate_limit,
            top_plays_per_candidate=top_plays,
        )
    except CandidateTargetNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Configuration or input error: {error}", file=sys.stderr)
        return 1
    except CandidateHydrationError as error:
        print(f"Candidate hydration failed: {error}", file=sys.stderr)
        return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Candidate discovery failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Candidate lookup failed. Check the PostgreSQL connection and schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hydrate bounded candidate top plays without similarity."
    )
    parser.add_argument("username", help="persisted target osu! username")
    parser.add_argument("--candidate-limit", type=int, default=20)
    parser.add_argument("--hydrate-limit", type=int, default=5)
    parser.add_argument("--top-plays", type=int, default=100)
    arguments = parser.parse_args()
    return asyncio.run(
        _run(
            arguments.username,
            arguments.candidate_limit,
            arguments.hydrate_limit,
            arguments.top_plays,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Developer command for bounded candidate-user discovery."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.discovery import (
    CandidateDiscoveryResult,
    CandidateTargetNotFoundError,
    discover_candidate_users,
)
from backend.app.osu.client import (
    OsuApiError,
    OsuAuthenticationError,
    OsuNetworkError,
)


def print_result(result: CandidateDiscoveryResult) -> None:
    """Print candidate identities without implying similarity."""
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Requested candidates: {result.requested_count}")
    print(f"Candidates returned: {len(result.candidates)}")
    print(f"Ranking requests: {result.ranking_requests_made}")

    for position, candidate in enumerate(result.candidates, start=1):
        username = candidate.username or "username unavailable"
        sources = ", ".join(candidate.sources)
        print(f"{position}. {username} ({candidate.user_id}) [{sources}]")


async def _run(username: str, limit: int) -> int:
    try:
        result = await discover_candidate_users(username, limit)
    except CandidateTargetNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Configuration or input error: {error}", file=sys.stderr)
        return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Candidate ranking acquisition failed: {error}", file=sys.stderr)
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
        description="Discover bounded candidate users without calculating similarity."
    )
    parser.add_argument("username", help="persisted target osu! username")
    parser.add_argument("--limit", type=int, default=100)
    arguments = parser.parse_args()
    return asyncio.run(_run(arguments.username, arguments.limit))


if __name__ == "__main__":
    raise SystemExit(main())

"""Developer command for target-map leaderboard candidate acquisition."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.target_maps import (
    TargetMapCandidateExperiment,
    TargetMapCandidateTargetNotFoundError,
    TargetMapEvidenceEmptyError,
    discover_target_map_candidates,
)
from backend.app.osu.client import (
    OsuApiError,
    OsuAuthenticationError,
    OsuNetworkError,
)


def print_result(result: TargetMapCandidateExperiment) -> None:
    """Print seed provenance and acquisition distribution without scores."""
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Seed beatmaps: {len(result.selected_seeds)}")
    print(f"Leaderboard requests: {result.leaderboard_requests_made}")
    print(f"Unique candidates discovered: {result.unique_candidate_count}")
    print(f"Candidates shown: {len(result.candidates)}")

    print("\nSeeds:")
    for index, seed in enumerate(result.selected_seeds, start=1):
        print(f"{index}. position #{seed.position} beatmap {seed.beatmap_id}")

    print("\nCandidates appearing on:")
    for hit_count, candidate_count in result.seed_hit_distribution:
        print(f"{hit_count} seeds: {candidate_count}")

    print("\nCandidates:")
    for index, candidate in enumerate(result.candidates, start=1):
        username = candidate.username or "username unavailable"
        seed_maps = ", ".join(str(value) for value in candidate.seed_beatmap_ids)
        print(f"{index}. {username} ({candidate.user_id})")
        print(f"   Seed hits: {candidate.seed_hit_count}")
        print(f"   Seed maps: {seed_maps}")


async def _run(username: str, seed_count: int, candidate_limit: int) -> int:
    try:
        result = await discover_target_map_candidates(
            username,
            seed_count=seed_count,
            candidate_limit=candidate_limit,
        )
    except (TargetMapCandidateTargetNotFoundError, TargetMapEvidenceEmptyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Configuration or input error: {error}", file=sys.stderr)
        return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Leaderboard candidate acquisition failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Target-map candidate lookup failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire candidates from persisted target-map leaderboards."
    )
    parser.add_argument("username", help="persisted target osu! username")
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=50)
    arguments = parser.parse_args()
    return asyncio.run(
        _run(arguments.username, arguments.seed_count, arguments.candidate_limit)
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Developer command for the top-play overlap similarity experiment."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import (
    OsuApiError,
    OsuAuthenticationError,
    OsuNetworkError,
)
from backend.app.similarity.overlap import (
    SimilarityExperimentResult,
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
    run_overlap_similarity_experiment,
)


def print_result(result: SimilarityExperimentResult) -> None:
    """Print overlap numbers without qualitative labels or verdicts."""
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Target top plays compared: {result.target_play_count}")
    print(f"Candidates hydrated: {len(result.candidates)}")
    print(f"Ranking requests: {result.ranking_requests_made}")
    print(f"Top-play requests: {result.top_play_requests_made}")

    for position, candidate in enumerate(result.candidates, start=1):
        username = candidate.username or "username unavailable"
        sources = ", ".join(candidate.sources)
        print(f"\n{position}. {username} ({candidate.user_id}) [{sources}]")
        print(f"   Candidate maps compared: {candidate.candidate_play_count}")
        print(f"   Shared maps: {candidate.shared_beatmap_count}")
        print(f"   Jaccard: {candidate.jaccard_similarity:.4f}")
        print(f"   Target coverage: {candidate.target_coverage:.2%}")


async def _run(
    username: str,
    candidate_limit: int,
    hydrate_limit: int,
    top_plays: int,
) -> int:
    try:
        result = await run_overlap_similarity_experiment(
            username,
            candidate_pool_limit=candidate_limit,
            hydrate_limit=hydrate_limit,
            comparison_top_plays=top_plays,
        )
    except (SimilarityTargetNotFoundError, TargetTopPlaysEmptyError) as error:
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
            "Similarity experiment failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare top-play beatmap overlap without recommendations."
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

"""Run one inspectable target/split for cross-target tie validation."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError
from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.cross_target_tie_validation import TARGETS, compact_summary
from backend.app.recommendation.discovery_tie_analysis import evaluate_discovery_ties
from backend.app.recommendation.verify_discovery_ties import print_result
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


async def _run(arguments: argparse.Namespace) -> int:
    if arguments.target not in TARGETS:
        print(f"Target must be one of: {', '.join(TARGETS)}", file=sys.stderr)
        return 1
    try:
        result = await evaluate_discovery_ties(arguments.target, split_index=arguments.split_index)
    except (SimilarityTargetNotFoundError, TargetTopPlaysEmptyError,
            SeedExcludedTargetEmptyError, RankedCandidatesEmptyError, ValueError) as error:
        print(str(error), file=sys.stderr); return 1
    except CandidateHydrationError as error:
        print(f"Candidate hydration failed: {error}", file=sys.stderr); return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Upstream request failed: {error}", file=sys.stderr); return 1
    except SQLAlchemyError:
        print("Experiment failed. Check PostgreSQL and its schema.", file=sys.stderr); return 1
    print_result(result)
    print(compact_summary(arguments.target, result))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded cross-target tie diagnostic.")
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--split-index", type=int, choices=range(5), default=0)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

"""Developer CLI for supporter-position positive prevalence."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.supporter_position_prevalence import (
    SPLITS,
    PrevalenceRunResult,
    evaluate_supporter_position_prevalence,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: PrevalenceRunResult) -> None:
    for item in result.provenance.positives:
        print(
            f"POSITION_PREVALENCE_POSITIVE target={result.target} "
            f"split={result.split_index} position={item.target_position} "
            f"beatmap={item.beatmap_id} best_supporter_position={item.best_supporter_position} "
            f"bucket={_bucket(item.best_supporter_position)} "
            f"support_structure={item.support_structure} "
            f"provenance={item.acquisition_classification} "
            f"best_supporter_rank={item.best_supporter_rank} "
            f"baseline_rank={item.baseline_rank}"
        )
    for analysis, summaries in (
        ("bucket", result.buckets),
        ("cumulative", result.cumulative),
        ("recurring_single", result.recurring_single),
        ("single_support", result.single_support),
        ("multi_support", result.multi_support),
    ):
        for item in summaries:
            print(
                f"POSITION_PREVALENCE target={result.target} split={result.split_index} "
                f"analysis={analysis} label={item.label} candidates={item.candidates} "
                f"positives={item.positives} prevalence={item.prevalence} "
                f"ratio={item.prevalence_ratio}"
            )
    print(
        f"POSITION_PREVALENCE_SUMMARY target={result.target} split={result.split_index} "
        f"candidates={len(result.provenance.candidates)} "
        f"positives={len(result.provenance.positives)} "
        f"ranks_unchanged={result.provenance.ranks_unchanged} "
        f"leaderboard={result.provenance.leaderboard_requests} "
        f"top_play={result.provenance.top_play_requests} "
        f"total={result.total_data_requests}"
    )


def _bucket(position: int | None) -> str:
    from backend.app.recommendation.supporter_position_prevalence import position_bucket
    return position_bucket(position)


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_supporter_position_prevalence(
            arguments.username, split_index=arguments.split_index
        )
    except (
        SimilarityTargetNotFoundError,
        TargetTopPlaysEmptyError,
        SeedExcludedTargetEmptyError,
        RankedCandidatesEmptyError,
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    except CandidateHydrationError as error:
        print(f"Candidate hydration failed: {error}", file=sys.stderr)
        return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Upstream request failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Experiment failed. Check PostgreSQL and its schema.", file=sys.stderr)
        return 1
    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure held-out-positive prevalence by supporter position."
    )
    parser.add_argument("username")
    parser.add_argument("--split-index", type=int, choices=SPLITS, required=True)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

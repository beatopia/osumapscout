"""Developer CLI for discovery-only candidate placement diagnostics."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.discovery_only_placement import (
    DiscoveryOnlyCandidate,
    DiscoveryOnlyPlacementResult,
    evaluate_discovery_only_placement,
)
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def _candidate(item: DiscoveryOnlyCandidate) -> str:
    return (
        f"beatmap={item.beatmap_id} rank={item.rank} support={item.support_count} "
        f"supporter_ranks={item.supporting_player_ranks} independent={item.total_independent_shared_count} "
        f"mean_independent={item.mean_independent_shared_count:.2f} best_player={item.best_supporting_player_rank} "
        f"iqr_count={item.attributes_within_iqr_count} iqr=({item.star_within_iqr},"
        f"{item.ar_within_iqr},{item.bpm_within_iqr}) deltas=({item.star_delta},"
        f"{item.ar_delta},{item.bpm_delta})"
    )


def print_result(result: DiscoveryOnlyPlacementResult) -> None:
    print("Population:")
    print(f"Discovery-only candidates: {len(result.candidates)}")
    print(f"Ranks: min={result.minimum_rank} median={result.median_rank} mean={result.mean_rank} max={result.maximum_rank}")
    print(f"Rank buckets: {result.rank_buckets}")
    print(f"Support distribution: {result.support_distribution}")
    print(f"Preference-fit distribution: {result.iqr_distribution}")
    print(f"Best-supporter-rank distribution: {result.best_supporter_distribution}")
    print("\nHeld-out discovery positives:")
    for positive in result.positives:
        print(f"split={positive.split_index} target_position={positive.target_position} {_candidate(positive.candidate)}")
        print(
            f"percentiles rank={positive.rank_percentile:.2f}% support={positive.support_percentile:.2f}% "
            f"independent={positive.independent_percentile:.2f}% iqr={positive.iqr_count_percentile:.2f}%"
        )
        print("above:")
        for item in positive.above: print(f"  {_candidate(item)}")
        print("below:")
        for item in positive.below: print(f"  {_candidate(item)}")
        print(f"immediate-above first difference: {positive.immediate_above_first_difference}")
        print(f"highest same-support: {_candidate(positive.highest_same_support) if positive.highest_same_support else None}")
        print(f"same-support first difference: {positive.same_support_first_difference}")
    print(f"\nPositive summary: {result.positive_summary}")
    print(f"Other summary: {result.other_summary}")
    print(f"First-difference counts: {result.first_difference_counts}")
    print("\nRequest cost:")
    print(f"Leaderboard requests: {result.leaderboard_requests}")
    print(f"Top-play requests: {result.top_play_requests}")
    print(f"Total data requests: {result.total_data_requests}")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_discovery_only_placement(
            arguments.username, top_plays=arguments.top_plays,
            holdout_count=arguments.holdout_count, split_count=arguments.split_count,
            split_index=arguments.split_index, seed_count=arguments.seed_count,
            candidate_top_plays=arguments.candidate_top_plays,
        )
    except (SimilarityTargetNotFoundError, TargetTopPlaysEmptyError,
            SeedExcludedTargetEmptyError, RankedCandidatesEmptyError, ValueError) as error:
        print(str(error), file=sys.stderr); return 1
    except CandidateHydrationError as error:
        print(f"Candidate hydration failed: {error}", file=sys.stderr); return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Upstream request failed: {error}", file=sys.stderr); return 1
    except SQLAlchemyError:
        print("Experiment failed. Check PostgreSQL and its schema.", file=sys.stderr); return 1
    print_result(result); return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Describe discovery-only candidate placement without changing ranking.")
    parser.add_argument("username")
    parser.add_argument("--top-plays", type=int, default=100)
    parser.add_argument("--holdout-count", type=int, default=10)
    parser.add_argument("--split-count", type=int, default=5)
    parser.add_argument("--split-index", type=int, default=0)
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--candidate-top-plays", type=int, default=100)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

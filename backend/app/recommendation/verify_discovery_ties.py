"""Developer CLI for discovery-only tie diagnostics."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError
from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.discovery_tie_analysis import DiscoveryTieResult, evaluate_discovery_ties
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: DiscoveryTieResult) -> None:
    print(f"Discovery-only candidates: {result.candidate_count}")
    print("Tie stages:")
    for item in result.stages:
        print(f"stage={item.stage} candidates={item.candidates_in_groups} groups={item.group_count} mean={item.mean_group_size:.2f} median={item.median_group_size:.2f} max={item.maximum_group_size}")
    print(f"Beatmap-ID dependent: {result.beatmap_id_dependent_count}/{result.candidate_count} ({result.beatmap_id_dependent_rate:.2%})")
    print("Largest Stage-4 groups:")
    for item in result.largest_stage4_groups:
        print(item)
    print("Continuous variation:")
    print(f"groups={len(result.stage4_groups)} star={result.star_varying_groups} ar={result.ar_varying_groups} bpm={result.bpm_varying_groups} any={result.any_varying_groups} identical_or_missing={result.identical_or_missing_groups}")
    print(f"dominance_groups={result.dominance_groups} dominated_candidates={result.dominated_candidates}")
    print(f"rank_spans mean={result.mean_rank_span:.2f} median={result.median_rank_span:.2f} max={result.maximum_rank_span}")
    print(f"Evidence completeness: {result.completeness}")
    print(f"Quantization: {result.quantization}")
    print("Known positives:")
    for item in result.positives:
        print(item)
    print("Request cost:")
    print(f"Leaderboard requests: {result.leaderboard_requests}")
    print(f"Top-play requests: {result.top_play_requests}")
    print(f"Total data requests: {result.total_data_requests}")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_discovery_ties(
            arguments.username, top_plays=arguments.top_plays,
            holdout_count=arguments.holdout_count, split_count=arguments.split_count,
            split_index=arguments.split_index, seed_count=arguments.seed_count,
            candidate_top_plays=arguments.candidate_top_plays,
        )
    except (SimilarityTargetNotFoundError, TargetTopPlaysEmptyError, SeedExcludedTargetEmptyError,
            RankedCandidatesEmptyError, ValueError) as error:
        print(str(error), file=sys.stderr); return 1
    except CandidateHydrationError as error:
        print(f"Candidate hydration failed: {error}", file=sys.stderr); return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Upstream request failed: {error}", file=sys.stderr); return 1
    except SQLAlchemyError:
        print("Experiment failed. Check PostgreSQL and its schema.", file=sys.stderr); return 1
    print_result(result); return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure discovery-only tie groups without reranking.")
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

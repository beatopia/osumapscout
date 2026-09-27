"""Developer CLI for expanded star-only tie-break validation."""

import argparse
import asyncio
import sys
from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.star_tiebreak_validation import (
    NEW_SPLITS, StarValidationResult, evaluate_star_validation,
)
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: StarValidationResult) -> None:
    for item in result.positives:
        print(
            f"STAR_POSITIVE target={result.target} split={result.split_index} position={item.target_position} "
            f"beatmap={item.beatmap_id} baseline_rank={item.baseline_rank} star_rank={item.star_rank} "
            f"change={item.signed_change('star')} group_size={item.group_size} "
            f"group_min={item.group_minimum_rank} group_max={item.group_maximum_rank} "
            f"baseline_group_position={item.baseline_group_position} star_group_position={item.star_group_position} "
            f"star_percentile={item.star_fit_percentile} star_delta={item.star_delta} "
            f"smaller_peers={item.peers_with_smaller_star_delta} larger_peers={item.peers_with_larger_star_delta} "
            f"support={item.support_count} iqr={item.attributes_within_iqr_count} "
            f"independent={item.total_independent_shared_count} best_player={item.best_supporting_player_rank}"
        )
    baseline = result.baseline.recovery; star = result.star.recovery
    print(
        f"STAR_VALIDATION_SUMMARY target={result.target} split={result.split_index} "
        f"held={baseline.held_out_count} recovered={baseline.recovered_anywhere} positives={len(result.positives)} "
        f"baseline_r10={baseline.recall_at_10:.6f} baseline_r30={baseline.recall_at_30:.6f} "
        f"baseline_r50={baseline.recall_at_50:.6f} baseline_r100={baseline.recall_at_100:.6f} "
        f"star_r10={star.recall_at_10:.6f} star_r30={star.recall_at_30:.6f} "
        f"star_r50={star.recall_at_50:.6f} star_r100={star.recall_at_100:.6f} "
        f"improved={result.direction.improved} worsened={result.direction.worsened} unchanged={result.direction.unchanged} "
        f"mean_change={result.direction.mean_signed} remaining_groups={result.remaining_ties.groups} "
        f"remaining_candidates={result.remaining_ties.candidates} candidate_equal={result.candidate_sets_equal} "
        f"outside_stable={result.outside_group_stable} leaderboard={result.leaderboard_requests} "
        f"top_play={result.top_play_requests} total={result.total_data_requests}"
    )


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_star_validation(arguments.username, split_index=arguments.split_index)
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
    parser = argparse.ArgumentParser(description="Validate star-only tie-breaking on new deterministic splits.")
    parser.add_argument("username")
    parser.add_argument("--split-index", type=int, choices=NEW_SPLITS, required=True)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

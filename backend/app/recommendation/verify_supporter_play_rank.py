"""Developer CLI for the supporter top-play-position experiment."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.supporter_play_rank_experiment import (
    NEW_SPLITS,
    SupporterPositionResult,
    evaluate_supporter_play_rank,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: SupporterPositionResult) -> None:
    for item in result.positives:
        positions = ",".join(str(value) for value in item.supporter_positions) or "missing"
        print(
            f"SUPPORTER_RANK_POSITIVE target={result.target} split={result.split_index} "
            f"position={item.target_position} beatmap={item.beatmap_id} "
            f"baseline_rank={item.baseline_rank} experimental_rank={item.experimental_rank} "
            f"change={item.signed_change} supporter_positions={positions} "
            f"best_top_play_position={item.best_position} mean_top_play_position={item.mean_position} "
            f"group_size={item.group_size} group_min={item.group_minimum_rank} "
            f"group_max={item.group_maximum_rank} "
            f"baseline_group_position={item.baseline_group_position} "
            f"experimental_group_position={item.experimental_group_position} "
            f"fit_percentile={item.fit_percentile:.6f} better_peers={item.peers_better} "
            f"worse_peers={item.peers_worse} tied_peers={item.peers_tied}"
        )

    baseline = result.baseline.recovery
    experimental = result.experimental.recovery
    buckets = ",".join(
        f"{label}:{count}" for label, count in result.distribution.buckets
    )
    print(
        f"SUPPORTER_RANK_SUMMARY target={result.target} split={result.split_index} "
        f"held={baseline.held_out_count} recovered={baseline.recovered_anywhere} "
        f"positives={len(result.positives)} baseline_r10={baseline.recall_at_10:.6f} "
        f"baseline_r30={baseline.recall_at_30:.6f} baseline_r50={baseline.recall_at_50:.6f} "
        f"baseline_r100={baseline.recall_at_100:.6f} "
        f"experimental_r10={experimental.recall_at_10:.6f} "
        f"experimental_r30={experimental.recall_at_30:.6f} "
        f"experimental_r50={experimental.recall_at_50:.6f} "
        f"experimental_r100={experimental.recall_at_100:.6f} "
        f"baseline_median={_rank_value(baseline, 'median')} "
        f"baseline_mean={_rank_value(baseline, 'mean')} "
        f"experimental_median={_rank_value(experimental, 'median')} "
        f"experimental_mean={_rank_value(experimental, 'mean')} "
        f"improved={result.direction.improved} worsened={result.direction.worsened} "
        f"unchanged={result.direction.unchanged} mean_change={result.direction.mean_signed} "
        f"before_groups={result.before_ties.groups} before_candidates={result.before_ties.candidates} "
        f"after_groups={result.after_ties.groups} after_candidates={result.after_ties.candidates} "
        f"position_buckets={buckets} position_missing={result.distribution.missing} "
        f"position_mean={result.distribution.mean} position_median={result.distribution.median} "
        f"position_min={result.distribution.minimum} position_max={result.distribution.maximum} "
        f"positive_best_mean={result.positive_population.mean_best} "
        f"positive_best_median={result.positive_population.median_best} "
        f"positive_mean_mean={result.positive_population.mean_mean} "
        f"positive_mean_median={result.positive_population.median_mean} "
        f"other_best_mean={result.other_population.mean_best} "
        f"other_best_median={result.other_population.median_best} "
        f"other_mean_mean={result.other_population.mean_mean} "
        f"other_mean_median={result.other_population.median_mean} "
        f"candidate_equal={result.candidate_sets_equal} recovery_equal={result.recovery_equal} "
        f"outside_stable={result.outside_group_stable} leaderboard={result.leaderboard_requests} "
        f"top_play={result.top_play_requests} total={result.total_data_requests}"
    )


def _rank_value(summary: object, name: str) -> float | None:
    ranks = getattr(summary, "recovered_rank_summary")
    return getattr(ranks, name) if ranks is not None else None


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_supporter_play_rank(
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
        description="Test supporter top-play position inside discovery-only ties."
    )
    parser.add_argument("username")
    parser.add_argument("--split-index", type=int, choices=NEW_SPLITS, required=True)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

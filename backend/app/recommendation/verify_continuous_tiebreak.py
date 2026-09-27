"""Developer CLI for single-field continuous tie-break experiments."""

import argparse
import asyncio
import sys
from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.continuous_tiebreak_experiment import (
    ContinuousTiebreakResult, evaluate_continuous_tiebreak,
)
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def _recall(result: ContinuousTiebreakResult, name: str) -> str:
    summary = getattr(result, name).recovery
    ranks = summary.recovered_rank_summary
    return (
        f"{name}_recovered={summary.recovered_anywhere} "
        f"{name}_r10={summary.recall_at_10:.6f} {name}_r30={summary.recall_at_30:.6f} "
        f"{name}_r50={summary.recall_at_50:.6f} {name}_r100={summary.recall_at_100:.6f} "
        f"{name}_median={ranks.median if ranks else 'none'} "
        f"{name}_mean={ranks.mean if ranks else 'none'}"
    )


def print_result(result: ContinuousTiebreakResult) -> None:
    print(f"candidate_sets_equal={result.candidate_sets_equal} outside_group_stable={result.outside_group_stable}")
    for name in ("baseline", "star", "ar", "bpm"):
        print(f"{name}: {getattr(result, name).recovery}")
    print(f"movements={result.movements}")
    print(f"remaining_ties={result.remaining_ties}")
    print(f"directions={result.directions}")
    print(f"transitions={result.transitions}")
    for item in result.positives:
        print(
            f"CONTINUOUS_POSITIVE target={result.target} split={result.split_index} "
            f"position={item.target_position} beatmap={item.beatmap_id} "
            f"baseline_rank={item.baseline_rank} star_rank={item.star_rank} "
            f"ar_rank={item.ar_rank} bpm_rank={item.bpm_rank} "
            f"star_change={item.star_rank-item.baseline_rank} "
            f"ar_change={item.ar_rank-item.baseline_rank} bpm_change={item.bpm_rank-item.baseline_rank} "
            f"group_size={item.group_size} group_min={item.group_minimum_rank} "
            f"group_max={item.group_maximum_rank} star_delta={item.star_delta} "
            f"ar_delta={item.ar_delta} bpm_delta={item.bpm_delta}"
        )
    print(
        f"CONTINUOUS_TIE_SUMMARY target={result.target} split={result.split_index} "
        f"positives={len(result.positives)} {_recall(result, 'baseline')} "
        f"{_recall(result, 'star')} {_recall(result, 'ar')} {_recall(result, 'bpm')} "
        + " ".join(
            f"{field}_remaining_groups={summary.groups} {field}_remaining_candidates={summary.candidates}"
            for field, summary in result.remaining_ties
        )
        + f" leaderboard={result.leaderboard_requests} top_play={result.top_play_requests} total={result.total_data_requests}"
    )


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_continuous_tiebreak(arguments.username, split_index=arguments.split_index)
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
    parser = argparse.ArgumentParser(description="Compare one-field tie-breaks inside discovery-only Stage-4 groups.")
    parser.add_argument("username")
    parser.add_argument("--split-index", type=int, choices=range(5), default=0)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

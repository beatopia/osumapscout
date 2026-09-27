"""Developer CLI for discovery-only provenance diagnostics."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.discovery_provenance_analysis import (
    SPLITS,
    ProvenanceRunResult,
    evaluate_discovery_provenance,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: ProvenanceRunResult) -> None:
    for item in result.positives:
        peers = item.peer_comparison
        print(
            f"PROVENANCE_POSITIVE target={result.target} split={result.split_index} "
            f"position={item.target_position} beatmap={item.beatmap_id} "
            f"baseline_rank={item.baseline_rank} support={item.support_count} "
            f"support_structure={item.support_structure} "
            f"supporter_ids={_values(item.supporter_user_ids)} "
            f"supporter_ranks={_values(item.supporter_ranks)} "
            f"best_supporter_rank={item.best_supporter_rank} "
            f"mean_supporter_rank={item.mean_supporter_rank:.6f} "
            f"supporter_positions={_values(item.supporter_positions)} "
            f"best_supporter_position={item.best_supporter_position} "
            f"mean_supporter_position={item.mean_supporter_position} "
            f"provenance={item.acquisition_classification} "
            f"supporter_provenance={_values(item.acquisition_groups)} "
            f"seed_hits={_values(item.seed_hit_counts)} "
            f"best_position_supporter_rank={item.best_position_supporter_rank} "
            f"aligned={item.best_position_supporter_is_best_similarity_supporter} "
            f"hydrated_supporters={item.hydrated_supporter_count} "
            f"selected_discovery_supporters={item.selected_discovery_supporter_count} "
            f"group_size={peers.group_size if peers else None} "
            f"peer_recurring={peers.recurring_only if peers else None} "
            f"peer_one_hit={peers.one_hit_only if peers else None} "
            f"peer_mixed={peers.mixed if peers else None} "
            f"peer_better_position={peers.better_top_play_position if peers else None} "
            f"peer_worse_position={peers.worse_top_play_position if peers else None}"
        )
    positive = result.positive_summary
    other = result.other_summary
    print(
        f"PROVENANCE_SUMMARY target={result.target} split={result.split_index} "
        f"candidates={len(result.candidates)} positives={len(result.positives)} "
        f"positive_single_rate={positive.single_support.rate:.6f} "
        f"other_single_rate={other.single_support.rate:.6f} "
        f"positive_recurring_rate={positive.recurring_only.rate:.6f} "
        f"other_recurring_rate={other.recurring_only.rate:.6f} "
        f"positive_one_hit_rate={positive.one_hit_only.rate:.6f} "
        f"other_one_hit_rate={other.one_hit_only.rate:.6f} "
        f"positive_mixed_rate={positive.mixed.rate:.6f} "
        f"other_mixed_rate={other.mixed.rate:.6f} "
        f"positive_best_rank_mean={positive.best_supporter_rank.mean} "
        f"other_best_rank_mean={other.best_supporter_rank.mean} "
        f"positive_best_position_mean={positive.best_supporter_position.mean} "
        f"other_best_position_mean={other.best_supporter_position.mean} "
        f"ranks_unchanged={result.ranks_unchanged} "
        f"leaderboard={result.leaderboard_requests} "
        f"top_play={result.top_play_requests} total={result.total_data_requests}"
    )
    for label, summary in (
        ("positive", result.positive_summary),
        ("other", result.other_summary),
    ):
        print(
            f"PROVENANCE_POPULATION target={result.target} split={result.split_index} "
            f"population={label} count={summary.count} "
            f"single={summary.single_support.count} multi={summary.multi_support.count} "
            f"recurring={summary.recurring_only.count} one_hit={summary.one_hit_only.count} "
            f"mixed={summary.mixed.count} unknown={summary.unknown.count} "
            f"best_rank_mean={summary.best_supporter_rank.mean} "
            f"best_rank_median={summary.best_supporter_rank.median} "
            f"mean_rank_mean={summary.mean_supporter_rank.mean} "
            f"mean_rank_median={summary.mean_supporter_rank.median} "
            f"support_mean={summary.support_count.mean} support_median={summary.support_count.median} "
            f"best_position_mean={summary.best_supporter_position.mean} "
            f"best_position_median={summary.best_supporter_position.median} "
            f"mean_position_mean={summary.mean_supporter_position.mean} "
            f"mean_position_median={summary.mean_supporter_position.median} "
            f"alignment_rate={summary.alignment_rate}"
        )
    for dimension, strata in (
        ("support", result.support_rank_strata),
        ("provenance", result.provenance_rank_strata),
        ("best_supporter_rank", result.supporter_rank_strata),
    ):
        for stratum in strata:
            print(
                f"PROVENANCE_RANK_STRATUM target={result.target} split={result.split_index} "
                f"dimension={dimension} stratum={stratum.name} count={stratum.count} "
                f"mean_rank={stratum.mean_rank} median_rank={stratum.median_rank}"
            )


def _values(values: tuple[object, ...]) -> str:
    return ",".join(str(value) for value in values) or "none"


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_discovery_provenance(
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
        description="Describe discovery-only supporter provenance without reranking."
    )
    parser.add_argument("username")
    parser.add_argument("--split-index", type=int, choices=SPLITS, required=True)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

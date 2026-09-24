"""Developer command for the selected-player expansion diagnostic."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.selection_expansion_analysis import (
    SelectionExpansionResult,
    evaluate_selection_expansion,
)
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: SelectionExpansionResult) -> None:
    print("Pool growth:")
    print(f"Top-10 candidates: {result.candidate_count_top10}")
    print(f"Top-15 candidates: {result.candidate_count_top15}")
    print(f"Intersection: {result.intersection_count}")
    print(f"Top-10 only: {result.top10_only_count}")
    print(f"New candidate maps: {result.top15_new_count}")
    print(f"Candidate-pool growth: {result.candidate_pool_growth}")
    print(f"Percentage pool growth: {result.candidate_pool_growth_rate:.2%}")

    print("\nNew-map provenance:")
    for item in result.new_candidates:
        print(
            f"beatmap={item.beatmap_id} support={item.support_count_top15} "
            f"best_player_rank={item.best_supporting_player_rank} "
            f"iqr_attributes={item.attributes_within_iqr_count} "
            f"preference_rank={item.preference_rank_top15}"
        )
    print(f"Distinct new maps by introducing rank: {result.new_map_origin_counts}")

    print("\nSupport effects:")
    unchanged = sum(item.support_delta == 0 for item in result.existing_map_changes)
    gained = sum(item.support_delta > 0 for item in result.existing_map_changes)
    intrinsic_anomalies = sum(
        not item.intrinsic_preference_unchanged for item in result.existing_map_changes
    )
    print(f"Existing maps with support unchanged: {unchanged}")
    print(f"Existing maps gaining support: {gained}")
    print(f"Support-delta distribution: {result.support_delta_distribution}")
    print(f"Support-tier transitions: {result.support_tier_transitions}")
    print(f"Intrinsic-preference anomalies: {intrinsic_anomalies}")

    print("\nRanking stability:")
    for item in result.top_n_stability:
        print(
            f"Top-{item.cutoff} overlap: {item.overlap_count}/{item.denominator} "
            f"({item.overlap_rate:.2%}); entering={item.entering_count}; "
            f"leaving={item.leaving_count}"
        )
    print(
        "Absolute rank change: "
        f"mean={result.rank_movement.mean_absolute_change:.2f}, "
        f"median={result.rank_movement.median_absolute_change:.2f}, "
        f"maximum={result.rank_movement.maximum_absolute_change}"
    )
    pressure_counts: dict[str, int] = {}
    for item in result.existing_map_changes:
        pressure_counts[item.pressure_cause] = pressure_counts.get(item.pressure_cause, 0) + 1
    print(f"Rank-pressure classifications: {tuple(sorted(pressure_counts.items()))}")

    print("\nHeld-out effects:")
    newly = sum(
        item.classification == "newly_recovered_by_expansion"
        for item in result.held_out_impacts
    )
    unchanged_ranks = sum(
        item.classification == "already_recovered" and item.rank_delta == 0
        for item in result.held_out_impacts
    )
    absent = sum(item.classification == "still_absent" for item in result.held_out_impacts)
    print(f"Newly recovered: {newly}")
    print(f"Already-recovered improved: {result.already_recovered_improved.count}")
    print(f"Already-recovered worsened: {result.already_recovered_worsened.count}")
    print(f"Already-recovered unchanged: {unchanged_ranks}")
    print(f"Still absent: {absent}")
    print(f"Improvement summary: {result.already_recovered_improved}")
    print(f"Regression summary: {result.already_recovered_worsened}")
    for item in result.held_out_impacts:
        print(
            f"position={item.play.position} beatmap={item.play.beatmap_id} "
            f"state={item.classification} top10_rank={item.top10_rank} "
            f"top15_rank={item.top15_rank} support10={item.support_top10} "
            f"support15={item.support_top15} rank_delta={item.rank_delta} "
            f"introduced_by_rank={item.introducing_player_rank}"
        )

    print("\nRequest cost:")
    print(f"Leaderboard requests: {result.leaderboard_requests}")
    print(f"Top-play requests: {result.top_play_requests}")
    print(f"Total data requests: {result.total_data_requests}")
    print("Authentication requests: not included in data-request counts")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_selection_expansion(
            arguments.username,
            top_plays=arguments.top_plays,
            holdout_count=arguments.holdout_count,
            split_count=arguments.split_count,
            split_index=arguments.split_index,
            seed_count=arguments.seed_count,
            candidate_top_plays=arguments.candidate_top_plays,
        )
    except (
        SimilarityTargetNotFoundError,
        TargetTopPlaysEmptyError,
        SeedExcludedTargetEmptyError,
        RankedCandidatesEmptyError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Configuration or input error: {error}", file=sys.stderr)
        return 1
    except CandidateHydrationError as error:
        print(f"Candidate hydration failed: {error}", file=sys.stderr)
        return 1
    except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"Upstream request failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Selection experiment failed. Check PostgreSQL and its schema.", file=sys.stderr)
        return 1
    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare selected-player limits 10 and 15 from one hydrated pool."
    )
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

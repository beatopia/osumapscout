"""Developer CLI for the discovery/ranking evidence separation experiment."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.discovery_ranking_separation import (
    DiscoveryRankingSeparationResult,
    evaluate_discovery_ranking_separation,
)
from backend.app.recommendation.holdout_recovery import OrderingRecoverySummary
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def _print_recovery(name: str, summary: OrderingRecoverySummary) -> None:
    rank = summary.recovered_rank_summary
    print(
        f"{name}: recovered={summary.recovered_anywhere}/{summary.held_out_count} "
        f"R@10={summary.recall_at_10:.2%} R@30={summary.recall_at_30:.2%} "
        f"R@50={summary.recall_at_50:.2%} R@100={summary.recall_at_100:.2%} "
        f"median={rank.median if rank else None} mean={rank.mean if rank else None}"
    )


def print_result(result: DiscoveryRankingSeparationResult) -> None:
    print("Candidate sets:")
    print(f"Top-10 candidates: {len(result.top10.preference)}")
    print(f"Full-top-15 candidates: {len(result.full15.preference)}")
    print(f"Hybrid candidates: {len(result.hybrid.preference)}")
    print(f"Full-top-15 new maps: {result.new_maps_full15}")
    print(f"Hybrid new maps: {result.new_maps_hybrid}")
    print(f"Hybrid equals full-top-15 candidate set: {result.candidate_sets_equal}")

    print("\nExisting-map evidence freeze:")
    print(f"Compared maps: {result.evidence_freeze.compared_maps}")
    print(f"Support anomalies: {result.evidence_freeze.support_anomalies}")
    print(f"Independent-shared anomalies: {result.evidence_freeze.independent_shared_anomalies}")
    print(f"Best-player-rank anomalies: {result.evidence_freeze.best_player_rank_anomalies}")
    print(f"Preference-evidence anomalies: {result.evidence_freeze.preference_anomalies}")

    print("\nRanking stability:")
    for name, stability, movement in (
        ("Full top 15", result.full15_stability, result.full15_movement),
        ("Hybrid", result.hybrid_stability, result.hybrid_movement),
    ):
        overlaps = ", ".join(f"top-{item.cutoff}={item.overlap_rate:.2%}" for item in stability)
        print(f"{name}: {overlaps}")
        print(
            f"{name} absolute movement: mean={movement.mean_absolute_change:.2f} "
            f"median={movement.median_absolute_change:.2f} max={movement.maximum_absolute_change}"
        )

    print("\nHeld-out maps:")
    for item in result.held_out_impacts:
        print(
            f"position={item.position} beatmap={item.beatmap_id} state={item.classification} "
            f"top10_rank={item.top10_rank} full15_rank={item.full15_rank} "
            f"hybrid_rank={item.hybrid_rank} introduced_by_rank={item.introducing_player_rank}"
        )
    print(f"Full-top-15 regression: {result.full15_regression}")
    print(f"Hybrid regression: {result.hybrid_regression}")

    print("\nRecovery metrics:")
    _print_recovery("Top 10", result.top10_recovery)
    _print_recovery("Full top 15", result.full15_recovery)
    _print_recovery("Hybrid", result.hybrid_recovery)

    print("\nRequest cost:")
    print(f"Leaderboard requests: {result.leaderboard_requests}")
    print(f"Top-play requests: {result.top_play_requests}")
    print(f"Total data requests: {result.total_data_requests}")
    print("Authentication requests: not included in data-request counts")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_discovery_ranking_separation(
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
    parser = argparse.ArgumentParser(description="Compare top-10, full-top-15, and discovery-expanded hybrid ranking views.")
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

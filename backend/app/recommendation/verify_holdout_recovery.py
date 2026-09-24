"""Developer command for held-out top-play recovery."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.holdout_recovery import (
    HoldoutRecoveryExperimentResult,
    OrderingRecoverySummary,
    evaluate_holdout_recovery,
)
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: HoldoutRecoveryExperimentResult) -> None:
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Original target plays: {result.original_target_play_count}")
    print(f"Training plays: {result.training_play_count}")
    print(f"Held-out plays: {result.held_out_play_count}")
    print(f"Configured splits: {result.split_count}")
    print(f"Current split: {result.split_index + 1} / {result.split_count}")
    current_positions = result.split_diagnostics.split_positions[result.split_index]
    print("Held-out positions for current split:")
    print(_positions(current_positions))
    print("All configured split positions:")
    for index, positions in enumerate(result.split_diagnostics.split_positions, 1):
        print(f"split {index}: {_positions(positions)}")
    print(
        "Unique positions covered across configured splits: "
        f"{result.split_diagnostics.unique_positions_covered} / "
        f"{result.split_diagnostics.target_count}"
    )
    print(f"Seeds selected from training evidence: {len(result.selected_seeds)}")
    print(f"Candidates hydrated: {result.candidates_hydrated}")
    print(f"Similar players used: {result.similar_players_used}")
    print(f"Leaderboard requests: {result.leaderboard_requests_made}")
    print(f"Top-play requests: {result.top_play_requests_made}")
    print(f"Additional recovery requests: {result.additional_recovery_requests}")
    print("\nHeld-out maps:")
    for index, recovery in enumerate(result.held_out_maps, 1):
        play = recovery.play
        identity = f"{play.artist or 'Unknown artist'} - {play.title or 'Unknown title'}"
        if play.difficulty_name:
            identity += f" [{play.difficulty_name}]"
        print(f"{index}. original position #{play.position}")
        print(f"   {identity}")
        print(f"   beatmap {play.beatmap_id}")
        print(f"   support-only rank: {_rank(recovery.support_only_rank)}")
        print(f"   evidence-aware rank: {_rank(recovery.evidence_aware_rank)}")
        print(f"   preference-aware rank: {_rank(recovery.preference_aware_rank)}")
        print(f"   support: {recovery.support_count or 0}")
    _print_summary("Support-only recovery", result.support_only_summary)
    _print_summary("Evidence-aware recovery", result.evidence_aware_summary)
    _print_summary("Preference-aware recovery", result.preference_aware_summary)
    print(format_split_summary(result))


def _positions(positions: tuple[int, ...]) -> str:
    return ", ".join(str(position) for position in positions)


def format_split_summary(result: HoldoutRecoveryExperimentResult) -> str:
    support = result.support_only_summary
    evidence = result.evidence_aware_summary
    preference = result.preference_aware_summary
    support_median = _summary_median(support)
    evidence_median = _summary_median(evidence)
    preference_median = _summary_median(preference)
    return (
        f"SPLIT_SUMMARY split={result.split_index} "
        f"heldout={result.held_out_play_count} "
        f"recovered={support.recovered_anywhere} "
        f"support_r10={support.recall_at_10:.4f} "
        f"support_r30={support.recall_at_30:.4f} "
        f"support_r50={support.recall_at_50:.4f} "
        f"support_r100={support.recall_at_100:.4f} "
        f"support_median={support_median} "
        f"evidence_recovered={evidence.recovered_anywhere} "
        f"evidence_r10={evidence.recall_at_10:.4f} "
        f"evidence_r30={evidence.recall_at_30:.4f} "
        f"evidence_r50={evidence.recall_at_50:.4f} "
        f"evidence_r100={evidence.recall_at_100:.4f} "
        f"evidence_median={evidence_median} "
        f"preference_recovered={preference.recovered_anywhere} "
        f"preference_r10={preference.recall_at_10:.4f} "
        f"preference_r30={preference.recall_at_30:.4f} "
        f"preference_r50={preference.recall_at_50:.4f} "
        f"preference_r100={preference.recall_at_100:.4f} "
        f"preference_median={preference_median}"
    )


def _summary_median(summary: OrderingRecoverySummary) -> str:
    ranks = summary.recovered_rank_summary
    return "unavailable" if ranks is None else f"{ranks.median:.1f}"


def _rank(value: int | None) -> str:
    return "not recovered" if value is None else f"#{value}"


def _print_summary(label: str, summary: OrderingRecoverySummary) -> None:
    print(f"\n{label}:")
    print(f"Recovered anywhere: {summary.recovered_anywhere} / {summary.held_out_count}")
    print(f"Recovery rate: {summary.recovery_rate:.2%}")
    for limit, count, recall in (
        (10, summary.recovered_at_10, summary.recall_at_10),
        (30, summary.recovered_at_30, summary.recall_at_30),
        (50, summary.recovered_at_50, summary.recall_at_50),
        (100, summary.recovered_at_100, summary.recall_at_100),
    ):
        print(f"Recovered@{limit}: {count}")
        print(f"Recall@{limit}: {recall:.2%}")
    ranks = summary.recovered_rank_summary
    if ranks is None:
        print("Recovered rank statistics: unavailable")
    else:
        print(f"Minimum recovered rank: {ranks.minimum}")
        print(f"Median recovered rank: {ranks.median:.2f}")
        print(f"Mean recovered rank: {ranks.mean:.2f}")
        print(f"Maximum recovered rank: {ranks.maximum}")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_holdout_recovery(
            arguments.username,
            top_plays=arguments.top_plays,
            holdout_count=arguments.holdout_count,
            split_count=arguments.split_count,
            split_index=arguments.split_index,
            seed_count=arguments.seed_count,
            hydration_budget=arguments.hydration_budget,
            candidate_top_plays=arguments.candidate_top_plays,
            similar_player_limit=arguments.similar_player_limit,
        )
    except (SimilarityTargetNotFoundError, TargetTopPlaysEmptyError,
            SeedExcludedTargetEmptyError, RankedCandidatesEmptyError) as error:
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
        print("Holdout recovery failed. Check PostgreSQL and its schema.", file=sys.stderr)
        return 1
    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate held-out target-map recovery.")
    parser.add_argument("username")
    parser.add_argument("--top-plays", type=int, default=100)
    parser.add_argument("--holdout-count", type=int, default=10)
    parser.add_argument("--split-count", type=int, default=5)
    parser.add_argument("--split-index", type=int, default=0)
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--hydration-budget", type=int, default=25)
    parser.add_argument("--candidate-top-plays", type=int, default=100)
    parser.add_argument("--similar-player-limit", type=int, default=10)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

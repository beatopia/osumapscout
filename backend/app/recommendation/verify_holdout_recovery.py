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
        print(f"   support: {recovery.support_count or 0}")
    _print_summary("Support-only recovery", result.support_only_summary)
    _print_summary("Evidence-aware recovery", result.evidence_aware_summary)


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
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--hydration-budget", type=int, default=25)
    parser.add_argument("--candidate-top-plays", type=int, default=100)
    parser.add_argument("--similar-player-limit", type=int, default=10)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

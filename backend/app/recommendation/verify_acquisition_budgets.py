"""Developer command for acquisition-budget sensitivity experiments."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.acquisition_budget_experiment import (
    AcquisitionBudgetExperimentResult,
    evaluate_acquisition_budgets,
    summarize_acquisition_requests,
)
from backend.app.recommendation.holdout_recovery import HoldoutRecoveryExperimentResult
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: AcquisitionBudgetExperimentResult) -> None:
    baseline_requests = _total_requests(result.results[0])
    for configuration, experiment in zip(
        result.configurations, result.results, strict=True
    ):
        summary = experiment.acquisition_summary
        preference = experiment.preference_aware_summary
        ranks = preference.recovered_rank_summary
        total_requests = _total_requests(experiment)
        print(f"\nConfiguration {configuration.label}:")
        print(f"Hydration budget: {configuration.hydration_budget}")
        print(f"Similar-player limit: {configuration.similar_player_limit}")
        print(f"Candidate users hydrated: {experiment.candidates_hydrated}")
        print(f"Selected similar players: {experiment.similar_players_used}")
        print(f"Leaderboard requests: {experiment.leaderboard_requests_made}")
        print(f"Top-play requests: {experiment.top_play_requests_made}")
        print(f"Additional diagnostic requests: {experiment.additional_recovery_requests}")
        print(f"Total data requests: {total_requests}")
        print(f"Request delta from baseline: {total_requests - baseline_requests:+d}")
        print(f"Held-out recovered anywhere: {summary.recovered} / {summary.held_out_total}")
        print(f"Absent from hydrated candidates: {summary.not_present_in_hydrated_candidates}")
        print(f"Present only in nonselected candidates: {summary.present_only_in_nonselected_candidates}")
        print(f"Extraction failures: {summary.extraction_or_exclusion_failures}")
        print(f"Recall@10: {preference.recall_at_10:.2%}")
        print(f"Recall@30: {preference.recall_at_30:.2%}")
        print(f"Recall@50: {preference.recall_at_50:.2%}")
        print(f"Recall@100: {preference.recall_at_100:.2%}")
        print(
            "Median recovered rank: "
            f"{ranks.median:.2f}" if ranks is not None else "Median recovered rank: unavailable"
        )
        print(
            "Mean recovered rank: "
            f"{ranks.mean:.2f}" if ranks is not None else "Mean recovered rank: unavailable"
        )

    print("\nHeld-out coverage transitions:")
    for transition in result.transitions:
        print(f"position #{transition.position}, beatmap {transition.beatmap_id}")
        print(
            f"   25/10: {transition.baseline_stage} "
            f"({_rank(transition.baseline_preference_rank)})"
        )
        print(
            f"   25/15: {transition.selected_limit_stage} "
            f"({_rank(transition.selected_limit_preference_rank)})"
        )
        print(
            f"   40/15: {transition.hydration_budget_stage} "
            f"({_rank(transition.hydration_budget_preference_rank)})"
        )
        print(f"   transition: {transition.cause}")

    request_summary = summarize_acquisition_requests(result.results)
    print("\nPer-split request totals:")
    print(f"Leaderboard requests: {request_summary.leaderboard_requests}")
    print(f"Top-play requests: {request_summary.top_play_requests}")
    print(f"Total data requests: {request_summary.total_data_requests}")
    print("Authentication requests: not included in data-request counts")


def _rank(value: int | None) -> str:
    return "not recovered" if value is None else f"preference rank #{value}"


def _total_requests(result: HoldoutRecoveryExperimentResult) -> int:
    return result.leaderboard_requests_made + result.top_play_requests_made


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_acquisition_budgets(
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
        print("Budget experiment failed. Check PostgreSQL and its schema.", file=sys.stderr)
        return 1
    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare three fixed acquisition-budget configurations."
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

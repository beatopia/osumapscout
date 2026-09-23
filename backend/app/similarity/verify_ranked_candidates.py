"""Developer command for the budgeted similar-player ranking experiment."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidateTargetNotFoundError,
    TargetMapEvidenceEmptyError,
)
from backend.app.osu.client import (
    OsuApiError,
    OsuAuthenticationError,
    OsuNetworkError,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import (
    RankedCandidateExperimentResult,
    RankedCandidatesEmptyError,
    evaluate_ranked_candidates,
)
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: RankedCandidateExperimentResult) -> None:
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Target maps compared: {result.target_play_count}")
    print(f"Unique candidates discovered: {result.discovered_candidate_count}")
    print(f"Recurring available: {result.recurring_candidate_count}")
    print(f"One-hit available: {result.one_hit_candidate_count}")
    print(f"Hydration budget: {result.hydration_budget}")
    print(f"Recurring selected: {result.recurring_selected_count}")
    print(f"One-hit selected: {result.one_hit_selected_count}")
    print(f"Candidates hydrated: {result.total_hydrated}")
    print(f"Leaderboard requests: {result.leaderboard_requests_made}")
    print(f"Top-play requests: {result.top_play_requests_made}")

    print("\nOne-hit hydration sample by seed:")
    for seed, count in result.one_hit_sample_by_seed:
        print(f"position #{seed.position} (beatmap {seed.beatmap_id}): {count}")

    print("\nSimilar-player ranking:")
    for rank, candidate in enumerate(result.candidates, start=1):
        username = candidate.username or "username unavailable"
        seed_maps = ", ".join(str(value) for value in candidate.seed_beatmap_ids)
        print(f"{rank}. {username} ({candidate.user_id})")
        print(f"   Acquisition: {candidate.acquisition_group}")
        print(f"   Seed hits: {candidate.seed_hit_count}")
        print(f"   Seed maps: {seed_maps}")
        print(f"   Candidate maps compared: {candidate.candidate_play_count}")
        print(f"   Raw shared maps: {candidate.raw_shared_beatmap_count}")
        print(f"   Raw Jaccard: {candidate.raw_jaccard_similarity:.4f}")
        print(f"   Raw target coverage: {candidate.raw_target_coverage:.2%}")
        print(
            "   Independent shared maps: "
            f"{candidate.seed_excluded_shared_beatmap_count}"
        )
        print(
            "   Seed-excluded Jaccard: "
            f"{candidate.seed_excluded_jaccard_similarity:.4f}"
        )
        print(
            "   Seed-excluded target coverage: "
            f"{candidate.seed_excluded_target_coverage:.2%}"
        )

    summary = result.summary
    print("\nSummary")
    print(f"Hydrated candidates: {summary.hydrated_count}")
    print(f"0 independent shared maps: {summary.zero_shared_count}")
    print(f"1+ independent shared maps: {summary.one_or_more_shared_count}")
    print(f"2+ independent shared maps: {summary.two_or_more_shared_count}")
    print(f"5+ independent shared maps: {summary.five_or_more_shared_count}")
    print(f"10+ independent shared maps: {summary.ten_or_more_shared_count}")
    print(f"Maximum independent shared maps: {summary.maximum_shared_count}")
    print(f"Median independent shared maps: {summary.median_shared_count:.2f}")
    print("\nTop 5:")
    print(f"recurring: {summary.top_five_groups.recurring}")
    print(f"one-hit: {summary.top_five_groups.one_hit}")
    print("\nTop 10:")
    print(f"recurring: {summary.top_ten_groups.recurring}")
    print(f"one-hit: {summary.top_ten_groups.one_hit}")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_ranked_candidates(
            arguments.username,
            seed_count=arguments.seed_count,
            hydration_budget=arguments.hydration_budget,
            top_plays=arguments.top_plays,
        )
    except (
        SimilarityTargetNotFoundError,
        TargetMapCandidateTargetNotFoundError,
        TargetMapEvidenceEmptyError,
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
        print(f"Target-map acquisition failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Ranked-candidate experiment failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank a bounded target-map candidate sample by overlap."
    )
    parser.add_argument("username", help="persisted target osu! username")
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--hydration-budget", type=int, default=25)
    parser.add_argument("--top-plays", type=int, default=100)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

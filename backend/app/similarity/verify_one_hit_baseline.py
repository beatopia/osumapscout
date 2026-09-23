"""Developer command for the recurring-versus-one-hit overlap baseline."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidateTargetNotFoundError,
    TargetMapEvidenceEmptyError,
    TargetMapSeed,
)
from backend.app.osu.client import (
    OsuApiError,
    OsuAuthenticationError,
    OsuNetworkError,
)
from backend.app.similarity.one_hit_baseline import (
    BaselineCandidatesEmptyError,
    OneHitBaselineResult,
    OverlapGroupSummary,
    evaluate_one_hit_baseline,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.target_map_overlap import (
    SeedExcludedTargetEmptyError,
    TargetMapCandidateOverlap,
)


def print_result(result: OneHitBaselineResult) -> None:
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Target maps compared: {result.target_play_count}")
    print(f"Unique candidates discovered: {result.discovered_candidate_count}")
    print(f"Recurring candidates available: {result.recurring_candidate_count}")
    print(f"One-hit candidates available: {result.one_hit_candidate_count}")
    print(f"Recurring evaluated: {len(result.recurring_candidates)}")
    print(f"One-hit evaluated: {len(result.one_hit_candidates)}")
    print(f"Leaderboard requests: {result.leaderboard_requests_made}")
    print(f"Top-play requests: {result.top_play_requests_made}")

    _print_seed_counts(
        "One-hit candidates available by seed",
        result.one_hit_available_by_seed,
    )
    _print_seed_counts("One-hit sample by seed", result.one_hit_sample_by_seed)

    _print_group("Recurring candidates", result.recurring_candidates)
    _print_group("One-hit baseline", result.one_hit_candidates)

    print("\nSummary")
    _print_summary("Recurring", result.recurring_summary)
    _print_summary("One-hit", result.one_hit_summary)


def _print_group(
    label: str,
    candidates: tuple[TargetMapCandidateOverlap, ...],
) -> None:
    print(f"\n{label}:")
    for index, candidate in enumerate(candidates, start=1):
        username = candidate.username or "username unavailable"
        seed_maps = ", ".join(str(value) for value in candidate.seed_beatmap_ids)
        print(f"{index}. {username} ({candidate.user_id})")
        print(f"   Seed hits: {candidate.seed_hit_count}")
        print(f"   Seed maps: {seed_maps}")
        print(f"   Candidate maps compared: {candidate.candidate_play_count}")
        print(f"   Raw shared maps: {candidate.raw_shared_beatmap_count}")
        print(f"   Raw Jaccard: {candidate.raw_jaccard_similarity:.4f}")
        print(
            "   Seed-excluded shared maps: "
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


def _print_summary(label: str, summary: OverlapGroupSummary) -> None:
    print(f"\n{label}:")
    print(f"Evaluated: {summary.evaluated_count}")
    print(f"0 shared: {summary.zero_shared_count}")
    print(f"1+ shared: {summary.one_or_more_shared_count}")
    print(f"2+ shared: {summary.two_or_more_shared_count}")
    print(f"5+ shared: {summary.five_or_more_shared_count}")
    print(f"Total shared: {summary.total_shared_count}")
    print(f"Mean shared: {summary.mean_shared_count:.2f}")
    print(f"Median shared: {summary.median_shared_count:.2f}")
    print(f"Maximum shared: {summary.maximum_shared_count}")


def _print_seed_counts(
    label: str,
    counts: tuple[tuple[TargetMapSeed, int], ...],
) -> None:
    print(f"\n{label}:")
    for seed, count in counts:
        print(f"position #{seed.position} (beatmap {seed.beatmap_id}): {count}")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_one_hit_baseline(
            arguments.username,
            seed_count=arguments.seed_count,
            recurring_limit=arguments.recurring_limit,
            one_hit_limit=arguments.one_hit_limit,
            top_plays=arguments.top_plays,
        )
    except (
        SimilarityTargetNotFoundError,
        TargetMapCandidateTargetNotFoundError,
        TargetMapEvidenceEmptyError,
        TargetTopPlaysEmptyError,
        SeedExcludedTargetEmptyError,
        BaselineCandidatesEmptyError,
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
            "One-hit baseline failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare recurring and stratified one-hit candidates."
    )
    parser.add_argument("username", help="persisted target osu! username")
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--recurring-limit", type=int, default=20)
    parser.add_argument("--one-hit-limit", type=int, default=15)
    parser.add_argument("--top-plays", type=int, default=100)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

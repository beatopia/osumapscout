"""Developer command for target-map candidate overlap evaluation."""

import argparse
import asyncio
import sys
from collections import Counter

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
from backend.app.similarity.target_map_overlap import (
    SeedExcludedTargetEmptyError,
    TargetMapOverlapExperimentResult,
    evaluate_target_map_candidates,
)


def print_result(result: TargetMapOverlapExperimentResult) -> None:
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Target maps compared: {result.target_play_count}")
    print(f"Seed maps: {len(result.selected_seeds)}")
    print(f"Target-map candidates discovered: {result.discovered_candidate_count}")
    print(f"Candidates evaluated: {len(result.candidates)}")
    print(f"Leaderboard requests: {result.leaderboard_requests_made}")
    print(f"Top-play requests: {result.top_play_requests_made}")

    print("\nSeeds:")
    for index, seed in enumerate(result.selected_seeds, start=1):
        print(f"{index}. position #{seed.position} beatmap {seed.beatmap_id}")

    for index, candidate in enumerate(result.candidates, start=1):
        username = candidate.username or "username unavailable"
        seed_maps = ", ".join(str(value) for value in candidate.seed_beatmap_ids)
        print(f"\n{index}. {username} ({candidate.user_id})")
        print(f"   Seed hits: {candidate.seed_hit_count}")
        print(f"   Seed maps: {seed_maps}")
        print(f"   Candidate maps compared: {candidate.candidate_play_count}")
        print(f"   Raw shared maps: {candidate.raw_shared_beatmap_count}")
        print(f"   Raw Jaccard: {candidate.raw_jaccard_similarity:.4f}")
        print(f"   Raw target coverage: {candidate.raw_target_coverage:.2%}")
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

    _print_summary(result)


def _print_summary(result: TargetMapOverlapExperimentResult) -> None:
    candidates = result.candidates
    print("\nSummary:")
    print(f"Evaluated candidates: {len(candidates)}")
    for label, values in (
        ("Raw overlap", [item.raw_shared_beatmap_count for item in candidates]),
        (
            "Seed-excluded overlap",
            [item.seed_excluded_shared_beatmap_count for item in candidates],
        ),
    ):
        print(f"\n{label}:")
        print(f"0 shared maps: {sum(value == 0 for value in values)}")
        print(f"1+ shared maps: {sum(value >= 1 for value in values)}")
        print(f"2+ shared maps: {sum(value >= 2 for value in values)}")
        print(f"5+ shared maps: {sum(value >= 5 for value in values)}")

    raw_max = max((item.raw_shared_beatmap_count for item in candidates), default=0)
    excluded_max = max(
        (item.seed_excluded_shared_beatmap_count for item in candidates),
        default=0,
    )
    print(f"\nMaximum raw shared maps: {raw_max}")
    print(f"Maximum seed-excluded shared maps: {excluded_max}")

    hit_counts = Counter(item.seed_hit_count for item in candidates)
    print("\nEvaluated acquisition evidence:")
    for hit_count in sorted(hit_counts, reverse=True):
        print(f"{hit_count}-hit candidates: {hit_counts[hit_count]}")


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_target_map_candidates(
            arguments.username,
            seed_count=arguments.seed_count,
            candidate_limit=arguments.candidate_limit,
            hydrate_limit=arguments.hydrate_limit,
            top_plays=arguments.top_plays,
        )
    except (
        SimilarityTargetNotFoundError,
        TargetMapCandidateTargetNotFoundError,
        TargetMapEvidenceEmptyError,
        TargetTopPlaysEmptyError,
        SeedExcludedTargetEmptyError,
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
            "Target-map overlap evaluation failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate target-map candidates without recommendations."
    )
    parser.add_argument("username", help="persisted target osu! username")
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=30)
    parser.add_argument("--hydrate-limit", type=int, default=10)
    parser.add_argument("--top-plays", type=int, default=100)
    arguments = parser.parse_args()
    return asyncio.run(_run(arguments))


if __name__ == "__main__":
    raise SystemExit(main())

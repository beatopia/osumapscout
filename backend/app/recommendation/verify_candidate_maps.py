"""Developer command for candidate-map extraction verification."""

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
from backend.app.recommendation.candidate_maps import (
    CandidateMap,
    CandidateMapExperimentResult,
    evaluate_candidate_maps,
    validate_show_maps,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: CandidateMapExperimentResult, show_maps: int) -> None:
    print(f"Target: {result.target_username} ({result.target_user_id})")
    print(f"Target top plays: {result.target_top_play_count}")
    print(f"Hydration budget: {result.hydration_budget}")
    print(f"Similar players hydrated: {result.similar_players_hydrated}")
    print(f"Similar players used: {result.similar_players_selected}")
    print(f"Leaderboard requests: {result.leaderboard_requests_made}")
    print(f"Top-play requests: {result.top_play_requests_made}")
    print(
        "Additional candidate-map requests: "
        f"{result.additional_extraction_requests}"
    )
    print(f"Candidate maps discovered: {result.summary.candidate_map_count}")

    print("\nSupport distribution:")
    print(f"1+ similar players: {result.summary.one_or_more_support_count}")
    print(f"2+ similar players: {result.summary.two_or_more_support_count}")
    print(f"3+ similar players: {result.summary.three_or_more_support_count}")
    print(f"5+ similar players: {result.summary.five_or_more_support_count}")
    print(f"Maximum support: {result.summary.maximum_support_count}")

    print("\nCandidate maps contributed by each selected player:")
    for contribution in result.contributions:
        username = contribution.username or "username unavailable"
        print(
            f"{username} (#{contribution.similar_player_rank}): "
            f"{contribution.candidate_map_count} candidate maps"
        )

    print("\nCandidate maps:")
    for index, candidate_map in enumerate(
        result.candidate_maps[:show_maps], start=1
    ):
        identity = _format_map_identity(candidate_map)
        print(f"{index}. {identity} (beatmap {candidate_map.beatmap_id})")
        print(f"   Support: {candidate_map.support_count} similar players")
        print(
            "   Best supporting player rank: "
            f"#{candidate_map.best_supporting_player_rank}"
        )
        print("   Supporting players:")
        for support in candidate_map.supports:
            username = support.username or "username unavailable"
            print(
                f"   {username} (#{support.similar_player_rank}, "
                f"{support.independent_shared_count} independent shared)"
            )


def _format_map_identity(candidate_map: CandidateMap) -> str:
    artist = candidate_map.artist or "Unknown artist"
    title = candidate_map.title or "Unknown title"
    difficulty = candidate_map.difficulty_name
    if difficulty:
        return f"{artist} - {title} [{difficulty}]"
    return f"{artist} - {title}"


async def _run(arguments: argparse.Namespace) -> int:
    try:
        validate_show_maps(arguments.show_maps)
        result = await evaluate_candidate_maps(
            arguments.username,
            seed_count=arguments.seed_count,
            hydration_budget=arguments.hydration_budget,
            top_plays=arguments.top_plays,
            similar_player_limit=arguments.similar_player_limit,
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
            "Candidate-map experiment failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result, arguments.show_maps)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract candidate maps from ranked similar players."
    )
    parser.add_argument("username", help="persisted target osu! username")
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--hydration-budget", type=int, default=25)
    parser.add_argument("--top-plays", type=int, default=100)
    parser.add_argument("--similar-player-limit", type=int, default=10)
    parser.add_argument("--show-maps", type=int, default=30)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

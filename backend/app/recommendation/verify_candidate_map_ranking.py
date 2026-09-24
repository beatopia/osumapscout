"""Developer command for candidate-map evidence-ranking comparison."""

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
from backend.app.recommendation.candidate_map_ranking import (
    CandidateMapEvidence,
    CandidateMapRankingExperimentResult,
    evaluate_candidate_map_ranking,
)
from backend.app.recommendation.candidate_maps import validate_show_maps
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(
    result: CandidateMapRankingExperimentResult,
    show_maps: int,
) -> None:
    extraction = result.extraction
    print(f"Target: {extraction.target_username} ({extraction.target_user_id})")
    print(f"Candidate maps: {extraction.summary.candidate_map_count}")
    print(f"Similar players used: {extraction.similar_players_selected}")
    print(f"Leaderboard requests: {extraction.leaderboard_requests_made}")
    print(f"Top-play requests: {extraction.top_play_requests_made}")
    print(
        "Additional extraction/ranking requests: "
        f"{extraction.additional_extraction_requests}"
    )

    print("\nT0026 support-only ordering:")
    for rank, candidate_map in enumerate(
        result.support_only_ordering[:show_maps], start=1
    ):
        print(
            f"{rank}. {_map_identity(candidate_map.artist, candidate_map.title, candidate_map.difficulty_name)} "
            f"(beatmap {candidate_map.beatmap_id}, support {candidate_map.support_count})"
        )

    print("\nT0027 evidence-aware ordering:")
    for item in result.evidence_aware_ordering[:show_maps]:
        candidate_map = item.candidate_map
        print(
            f"{item.evidence_rank}. "
            f"{_map_identity(candidate_map.artist, candidate_map.title, candidate_map.difficulty_name)}"
        )
        print(f"   Beatmap ID: {candidate_map.beatmap_id}")
        print(f"   Support: {item.support_count}")
        print(
            "   Total independent shared: "
            f"{item.total_independent_shared_count}"
        )
        print(
            "   Mean independent shared: "
            f"{item.mean_independent_shared_count:.2f}"
        )
        print(
            "   Best supporting-player rank: "
            f"#{item.best_supporting_player_rank}"
        )
        print(
            "   Mean supporting-player rank: "
            f"{item.mean_supporting_player_rank:.2f}"
        )
        print(f"   Previous support-only rank: #{item.support_only_rank}")
        print(f"   Rank change: {item.rank_delta:+d}")

    _print_movements("Top 10 maps that moved upward most", result.largest_upward_moves)
    _print_movements(
        "Top 10 maps that moved downward most",
        result.largest_downward_moves,
    )


def _print_movements(label: str, items: tuple[CandidateMapEvidence, ...]) -> None:
    print(f"\n{label}:")
    if not items:
        print("None")
        return
    for item in items:
        print(
            f"beatmap {item.candidate_map.beatmap_id}: "
            f"old #{item.support_only_rank} -> new #{item.evidence_rank} "
            f"({item.rank_delta:+d}), support {item.support_count}, "
            f"total independent {item.total_independent_shared_count}"
        )


def _map_identity(
    artist: str | None,
    title: str | None,
    difficulty_name: str | None,
) -> str:
    identity = f"{artist or 'Unknown artist'} - {title or 'Unknown title'}"
    if difficulty_name:
        return f"{identity} [{difficulty_name}]"
    return identity


async def _run(arguments: argparse.Namespace) -> int:
    try:
        validate_show_maps(arguments.show_maps)
        result = await evaluate_candidate_map_ranking(
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
            "Candidate-map ranking failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1

    print_result(result, arguments.show_maps)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare support-only and evidence-aware candidate-map ranks."
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

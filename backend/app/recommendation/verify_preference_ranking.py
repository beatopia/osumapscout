"""Developer command for preference-aware candidate-map ranking."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidateTargetNotFoundError,
    TargetMapEvidenceEmptyError,
)
from backend.app.osu.client import OsuApiError, OsuAuthenticationError, OsuNetworkError
from backend.app.recommendation.preference_ranking import (
    PreferenceRankingExperimentResult,
    evaluate_preference_ranking,
)
from backend.app.similarity.overlap import SimilarityTargetNotFoundError, TargetTopPlaysEmptyError
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: PreferenceRankingExperimentResult) -> None:
    profile = result.target_profile
    extraction = result.evidence.ranking.extraction
    print(f"Target: {profile.username} ({profile.user_id})")
    print(f"Target plays analyzed: {profile.top_play_count}")
    print(f"Candidate maps: {len(result.preference_aware_ordering)}")
    print(f"Similar players used: {extraction.similar_players_selected}")
    print(f"Leaderboard requests: {extraction.leaderboard_requests_made}")
    print(f"Top-play requests: {extraction.top_play_requests_made}")
    print(
        "Additional preference-ranking requests: "
        f"{result.additional_preference_ranking_requests}"
    )
    print("\nPreference-aware candidate maps:")
    for ranked in result.preference_aware_ordering[: result.show_maps]:
        preference = ranked.preference_evidence
        collaborative = preference.collaborative
        candidate = collaborative.candidate_map
        identity = f"{candidate.artist or 'Unknown artist'} - {candidate.title or 'Unknown title'}"
        if candidate.difficulty_name:
            identity += f" [{candidate.difficulty_name}]"
        print(f"{ranked.preference_rank}. {identity}")
        print(f"   Beatmap ID: {candidate.beatmap_id}")
        print(f"   Collaborative support: {collaborative.support_count}")
        print(
            "   Attributes within target IQR: "
            f"{preference.attributes_within_iqr_count}"
        )
        print(f"   Stars within IQR: {_within(preference.star_rating.within_target_iqr)}")
        print(f"   AR within IQR: {_within(preference.approach_rate.within_target_iqr)}")
        print(f"   BPM within IQR: {_within(preference.bpm.within_target_iqr)}")
        print(f"   Previous evidence-aware rank: #{collaborative.evidence_rank}")
        print(f"   Preference-aware rank: #{ranked.preference_rank}")
        print(f"   Rank delta: {ranked.rank_delta:+d}")


def _within(value: bool | None) -> str:
    if value is None:
        return "unavailable"
    return "yes" if value else "no"


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_preference_ranking(
            arguments.username,
            seed_count=arguments.seed_count,
            hydration_budget=arguments.hydration_budget,
            top_plays=arguments.top_plays,
            similar_player_limit=arguments.similar_player_limit,
            show_maps=arguments.show_maps,
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
            "Preference-ranking experiment failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1
    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare evidence-aware and preference-aware map ordering."
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

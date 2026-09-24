"""Developer command for target preference evidence inspection."""

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
from backend.app.recommendation.preference_evidence import (
    NumericCandidateEvidence,
    NumericPreferenceSummary,
    PreferenceEvidenceExperimentResult,
    PreferencePoolSummary,
    evaluate_preference_evidence,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError


def print_result(result: PreferenceEvidenceExperimentResult) -> None:
    profile = result.target_profile
    extraction = result.ranking.extraction
    print(f"Target: {profile.username} ({profile.user_id})")
    print(f"Target plays analyzed: {profile.top_play_count}")
    print(f"Candidate maps: {len(result.candidates)}")
    print(f"Similar players used: {extraction.similar_players_selected}")
    print(f"Leaderboard requests: {extraction.leaderboard_requests_made}")
    print(f"Top-play requests: {extraction.top_play_requests_made}")
    print(
        "Additional preference-evidence requests: "
        f"{result.additional_preference_requests}"
    )

    print("\nTarget map profile:")
    _print_numeric_summary("Stars", profile.star_rating)
    _print_numeric_summary("AR", profile.approach_rate)
    _print_numeric_summary("BPM", profile.bpm)
    print("\nExact mod combinations:")
    for item in profile.exact_mod_combinations:
        print(f"{_mods_label(item.mods)}: {item.count}")
    print("\nIndividual mods:")
    if profile.individual_mods:
        for item in profile.individual_mods:
            print(f"{item.acronym}: {item.count}")
    else:
        print("(none)")
    top_combo = profile.top_exact_mod_combination
    print(
        "Most common exact mod combination: "
        f"{_mods_label(top_combo) if top_combo is not None else 'unavailable'}"
    )

    _print_pool_summary("Whole candidate pool", result.whole_pool_summary)
    _print_pool_summary("Top displayed maps", result.displayed_prefix_summary)

    print("\nCandidate preference evidence:")
    for candidate in result.candidates[: result.show_maps]:
        collaborative = candidate.collaborative
        candidate_map = collaborative.candidate_map
        print(
            f"{collaborative.evidence_rank}. "
            f"{_map_identity(candidate_map.artist, candidate_map.title, candidate_map.difficulty_name)}"
        )
        print(f"   Beatmap ID: {candidate_map.beatmap_id}")
        print(f"   Collaborative rank: #{collaborative.evidence_rank}")
        print(f"   Support: {collaborative.support_count}")
        _print_candidate_numeric("Stars", candidate.star_rating, profile.star_rating)
        _print_candidate_numeric("AR", candidate.approach_rate, profile.approach_rate)
        _print_candidate_numeric("BPM", candidate.bpm, profile.bpm)
        print(
            "   Attributes within IQR: "
            f"{candidate.attributes_within_iqr_count} / "
            f"{candidate.comparable_attribute_count}"
        )
        print("   Supporting mod combos:")
        for item in candidate.exact_supporting_mod_combinations:
            print(f"   {_mods_label(item.mods)}: {item.count}")
        matched = candidate.supports_using_target_top_mod_combo
        print(
            "   Supports using target top mod combo: "
            f"{matched if matched is not None else 'unavailable'}"
        )


def _print_numeric_summary(
    label: str,
    summary: NumericPreferenceSummary | None,
) -> None:
    print(f"\n{label}:")
    if summary is None:
        print("unavailable")
        return
    print(f"count: {summary.count}")
    print(f"min: {summary.minimum:.2f}")
    print(f"Q1: {summary.first_quartile:.2f}")
    print(f"median: {summary.median:.2f}")
    print(f"Q3: {summary.third_quartile:.2f}")
    print(f"max: {summary.maximum:.2f}")
    print(f"mean: {summary.mean:.2f}")


def _print_candidate_numeric(
    label: str,
    evidence: NumericCandidateEvidence,
    target: NumericPreferenceSummary | None,
) -> None:
    value = "unavailable" if evidence.value is None else f"{evidence.value:.2f}"
    median_value = "unavailable" if target is None else f"{target.median:.2f}"
    delta = (
        "unavailable"
        if evidence.delta_from_target_median is None
        else f"{evidence.delta_from_target_median:.2f}"
    )
    within = (
        "unavailable"
        if evidence.within_target_iqr is None
        else "yes" if evidence.within_target_iqr else "no"
    )
    print(f"   {label}: {value}")
    print(f"   Target median {label.lower()}: {median_value}")
    print(f"   Delta: {delta}")
    print(f"   Within target {label.lower()} IQR: {within}")


def _print_pool_summary(label: str, summary: PreferencePoolSummary) -> None:
    print(f"\n{label}:")
    print(
        f"within star IQR: {summary.star_within_iqr_count} / "
        f"{summary.star_metadata_count} available "
        f"({summary.star_metadata_missing_count} missing)"
    )
    print(
        f"within AR IQR: {summary.ar_within_iqr_count} / "
        f"{summary.ar_metadata_count} available "
        f"({summary.ar_metadata_missing_count} missing)"
    )
    print(
        f"within BPM IQR: {summary.bpm_within_iqr_count} / "
        f"{summary.bpm_metadata_count} available "
        f"({summary.bpm_metadata_missing_count} missing)"
    )
    print(
        "within all available target IQRs: "
        f"{summary.within_all_available_target_iqrs_count}"
    )
    print("Attributes-within-IQR distribution:")
    for count, candidates in summary.iqr_count_distribution:
        print(f"{count} attributes: {candidates}")


def _mods_label(mods: tuple[str, ...]) -> str:
    return "".join(mods) if mods else "NM"


def _map_identity(
    artist: str | None,
    title: str | None,
    difficulty_name: str | None,
) -> str:
    identity = f"{artist or 'Unknown artist'} - {title or 'Unknown title'}"
    return f"{identity} [{difficulty_name}]" if difficulty_name else identity


async def _run(arguments: argparse.Namespace) -> int:
    try:
        result = await evaluate_preference_evidence(
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
            "Preference-evidence experiment failed. Check PostgreSQL and its schema.",
            file=sys.stderr,
        )
        return 1
    print_result(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare candidate maps with persisted target preferences."
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

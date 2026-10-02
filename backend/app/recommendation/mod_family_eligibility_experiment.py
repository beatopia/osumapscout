"""Offline gameplay-mod-family eligibility experiment for similar players."""

from collections import Counter
from dataclasses import dataclass, replace

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.effective_attributes import effective_attributes
from backend.app.recommendation.holdout_recovery import (
    OrderingRecoverySummary,
    TargetPlayEvidence,
    evaluate_holdout_recovery,
    summarize_recovery,
)
from backend.app.recommendation.preference_evidence import (
    NumericPreferenceSummary,
    calculate_numeric_summary,
)
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate
from backend.app.recommendation.service import build_hybrid_ranking
from backend.app.similarity.ranked_candidates import (
    RankedCandidateExperimentResult,
    RankedSimilarPlayer,
)
from backend.app.similarity.gameplay_mods import normalize_gameplay_mods

MIN_MATCH_SHARE = 0.5


@dataclass(frozen=True)
class PlayerModCompatibility:
    baseline_rank: int
    user_id: int
    username: str | None
    independent_overlap: int
    dominant_exact_mods: tuple[str, ...]
    dominant_normalized_mods: tuple[str, ...]
    target_normalized_share: float
    effective_ar: NumericPreferenceSummary | None
    effective_bpm: NumericPreferenceSummary | None
    pp: NumericPreferenceSummary | None
    eligible: bool


@dataclass(frozen=True)
class ModFamilyEligibilityResult:
    target_username: str
    split_index: int
    target_exact_mods: tuple[str, ...]
    target_normalized_mods: tuple[str, ...]
    target_normalized_share: float
    hydrated_count: int
    eligible_count: int
    baseline_players: tuple[PlayerModCompatibility, ...]
    eligible_players: tuple[PlayerModCompatibility, ...]
    baseline_recovery: OrderingRecoverySummary
    eligible_recovery: OrderingRecoverySummary
    baseline_candidate_maps: int
    eligible_candidate_maps: int
    leaderboard_requests: int
    hydration_requests: int


def target_style(
    plays: tuple[TargetPlayEvidence, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], float]:
    exact = Counter(play.mods for play in plays)
    primary_exact = min(exact, key=lambda value: (-exact[value], value)) if exact else ()
    normalized = normalize_gameplay_mods(primary_exact)
    share = (
        sum(normalize_gameplay_mods(play.mods) == normalized for play in plays) / len(plays)
        if plays else 0.0
    )
    return primary_exact, normalized, share


def describe_player(
    rank: int,
    player: RankedSimilarPlayer,
    target_normalized: tuple[str, ...],
    minimum_share: float = MIN_MATCH_SHARE,
) -> PlayerModCompatibility:
    plays = player.hydrated_top_plays
    normalized = Counter(normalize_gameplay_mods(play.mods) for play in plays)
    exact = Counter(play.mods for play in plays)
    dominant_exact = min(exact, key=lambda value: (-exact[value], value)) if exact else ()
    dominant_normalized = min(
        normalized, key=lambda value: (-normalized[value], value)
    ) if normalized else ()
    share = normalized[target_normalized] / len(plays) if plays else 0.0
    effective = tuple(
        effective_attributes(play.approach_rate, play.bpm, play.mods)
        for play in plays
    )
    return PlayerModCompatibility(
        rank, player.user_id, player.username, player.seed_excluded_shared_beatmap_count,
        dominant_exact, dominant_normalized, share,
        calculate_numeric_summary(item.effective_ar for item in effective),
        calculate_numeric_summary(item.effective_bpm for item in effective),
        calculate_numeric_summary(play.performance_points for play in plays),
        dominant_normalized == target_normalized and share >= minimum_share,
    )


async def evaluate_mod_family_eligibility(
    username: str,
    *,
    split_index: int,
    osu_client: OsuApiClient | None = None,
) -> ModFamilyEligibilityResult:
    recovery = await evaluate_holdout_recovery(
        username, top_plays=100, holdout_count=10, split_count=8,
        split_index=split_index, seed_count=5, hydration_budget=25,
        candidate_top_plays=100, similar_player_limit=15,
        osu_client=osu_client or OsuApiClient(OsuCredentials.from_environment()),
    )
    ranking = recovery.ranking_result
    profile = recovery.target_preference_profile
    if ranking is None or profile is None:
        raise ValueError("Holdout result lacks ranking or preference evidence.")
    exact, normalized, share = target_style(recovery.training_plays)
    described = tuple(
        describe_player(rank, player, normalized)
        for rank, player in enumerate(ranking.candidates, 1)
    )
    eligible_ids = {item.user_id for item in described if item.eligible}
    eligible_candidates = tuple(
        player for player in ranking.candidates if player.user_id in eligible_ids
    )
    eligible_ranking: RankedCandidateExperimentResult = replace(
        ranking, candidates=eligible_candidates
    )
    baseline_maps = build_hybrid_ranking(ranking, profile)
    eligible_maps = build_hybrid_ranking(eligible_ranking, profile)
    held_out = tuple(item.play.beatmap_id for item in recovery.held_out_maps)
    return ModFamilyEligibilityResult(
        recovery.target_username, split_index, exact, normalized, share,
        len(described), len(eligible_candidates), described[:15],
        tuple(item for item in described if item.eligible)[:15],
        summarize_recovery(held_out, _map_ids(baseline_maps)),
        summarize_recovery(held_out, _map_ids(eligible_maps)),
        len(baseline_maps), len(eligible_maps), recovery.leaderboard_requests_made,
        recovery.top_play_requests_made,
    )


def _map_ids(items: tuple[PreferenceRankedCandidate, ...]) -> tuple[int, ...]:
    return tuple(
        item.preference_evidence.collaborative.candidate_map.beatmap_id
        for item in items
    )

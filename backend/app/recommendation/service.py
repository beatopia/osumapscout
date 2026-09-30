"""Application-facing recommendation generation using the frozen MVP policy."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from backend.app.analysis.statistics import TopPlayStatisticsInput
from backend.app.database.persistence import persist_user_top_plays
from backend.app.osu.client import OsuApiClient, OsuCredentials, OsuTopPlay, OsuUserProfile
from backend.app.recommendation.candidate_map_ranking import rank_candidate_map_evidence
from backend.app.recommendation.candidate_maps import extract_candidate_maps
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    TargetPreferenceProfile,
    annotate_candidate_evidence,
    build_target_preference_profile,
)
from backend.app.recommendation.preference_ranking import (
    PreferenceRankedCandidate,
    rank_candidate_map_preferences,
)
from backend.app.similarity.ranked_candidates import (
    RankedCandidateExperimentResult,
    evaluate_ranked_candidates,
)

TARGET_TOP_PLAYS = 100
SEED_COUNT = 5
HYDRATION_BUDGET = 25
CANDIDATE_TOP_PLAYS = 100
RANKING_PLAYER_LIMIT = 10
DISCOVERY_PLAYER_LIMIT = 15
DEFAULT_LIMIT = 20
MAXIMUM_LIMIT = 100


@dataclass(frozen=True)
class RefreshedTarget:
    profile: OsuUserProfile
    top_plays: tuple[OsuTopPlay, ...]


@dataclass(frozen=True)
class Recommendation:
    rank: int
    beatmap_id: int
    artist: str | None
    title: str | None
    difficulty_name: str | None
    star_rating: float | None
    approach_rate: float | None
    bpm: float | None
    support_count: int
    best_supporting_player_rank: int
    attributes_within_iqr_count: int
    why_recommended: str


@dataclass(frozen=True)
class RecommendationRequestAccounting:
    profile_requests: int
    target_top_play_requests: int
    leaderboard_requests: int
    candidate_top_play_requests: int


@dataclass(frozen=True)
class RecommendationContext:
    discovered_candidate_users: int
    hydrated_candidate_users: int
    ranking_similar_players: int
    discovery_similar_players: int
    candidate_map_count: int
    returned_recommendation_count: int


@dataclass(frozen=True)
class RecommendationResult:
    target_username: str
    target_user_id: int
    recommendations: tuple[Recommendation, ...]
    context: RecommendationContext
    requests: RecommendationRequestAccounting


RefreshFunction = Callable[[str, OsuApiClient], Awaitable[RefreshedTarget]]
RankingFunction = Callable[..., Awaitable[RankedCandidateExperimentResult]]


async def refresh_target_user(
    username: str, client: OsuApiClient
) -> RefreshedTarget:
    """Refresh one complete target snapshot using existing transactional semantics."""
    profile = await client.get_user_by_username(username)
    plays = tuple(
        await client.get_top_plays_by_user_id(profile.user_id, limit=TARGET_TOP_PLAYS)
    )
    persist_user_top_plays(profile, plays)
    return RefreshedTarget(profile, plays)


async def generate_recommendations(
    username: str,
    *,
    limit: int = DEFAULT_LIMIT,
    osu_client: OsuApiClient | None = None,
    refresh_function: RefreshFunction = refresh_target_user,
    ranking_function: RankingFunction = evaluate_ranked_candidates,
) -> RecommendationResult:
    """Refresh the target and generate one on-demand deterministic ranking."""
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_limit(limit)
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    target = await refresh_function(requested_username, client)
    profile = _preference_profile(target)
    ranking = await ranking_function(
        target.profile.username,
        seed_count=SEED_COUNT,
        hydration_budget=HYDRATION_BUDGET,
        top_plays=CANDIDATE_TOP_PLAYS,
        osu_client=client,
    )
    ordered = build_hybrid_ranking(ranking, profile)
    recommendations = tuple(
        _to_recommendation(item) for item in ordered[:limit]
    )
    return RecommendationResult(
        target_username=target.profile.username,
        target_user_id=target.profile.user_id,
        recommendations=recommendations,
        context=RecommendationContext(
            discovered_candidate_users=ranking.discovered_candidate_count,
            hydrated_candidate_users=ranking.total_hydrated,
            ranking_similar_players=min(RANKING_PLAYER_LIMIT, ranking.total_hydrated),
            discovery_similar_players=min(DISCOVERY_PLAYER_LIMIT, ranking.total_hydrated),
            candidate_map_count=len(ordered),
            returned_recommendation_count=len(recommendations),
        ),
        requests=RecommendationRequestAccounting(
            profile_requests=1,
            target_top_play_requests=1,
            leaderboard_requests=ranking.leaderboard_requests_made,
            candidate_top_play_requests=ranking.top_play_requests_made,
        ),
    )


def build_hybrid_ranking(
    ranking: RankedCandidateExperimentResult,
    profile: TargetPreferenceProfile,
) -> tuple[PreferenceRankedCandidate, ...]:
    """Use top ten evidence plus maps discovered only by players 11 through 15."""
    native = _build_evidence(ranking, profile, RANKING_PLAYER_LIMIT)
    expanded = _build_evidence(ranking, profile, DISCOVERY_PLAYER_LIMIT)
    native_ids = {_beatmap_id(item) for item in native}
    hybrid = tuple(item.preference_evidence for item in native) + tuple(
        item.preference_evidence
        for item in expanded
        if _beatmap_id(item) not in native_ids
    )
    return rank_candidate_map_preferences(hybrid)


def _build_evidence(
    ranking: RankedCandidateExperimentResult,
    profile: TargetPreferenceProfile,
    player_limit: int,
) -> tuple[PreferenceRankedCandidate, ...]:
    maps = extract_candidate_maps(ranking, player_limit).candidate_maps
    collaborative = rank_candidate_map_evidence(maps)
    return rank_candidate_map_preferences(
        annotate_candidate_evidence(collaborative, profile)
    )


def _preference_profile(target: RefreshedTarget) -> TargetPreferenceProfile:
    inputs = tuple(
        TopPlayStatisticsInput(
            performance_points=play.performance_points,
            accuracy=play.accuracy,
            star_rating=play.star_rating,
            approach_rate=play.approach_rate,
            bpm=play.bpm,
            mods=play.mods,
        )
        for play in target.top_plays
    )
    return build_target_preference_profile(
        target.profile.user_id, target.profile.username, inputs
    )


def _to_recommendation(item: PreferenceRankedCandidate) -> Recommendation:
    evidence = item.preference_evidence
    candidate = evidence.collaborative.candidate_map
    return Recommendation(
        rank=item.preference_rank,
        beatmap_id=candidate.beatmap_id,
        artist=candidate.artist,
        title=candidate.title,
        difficulty_name=candidate.difficulty_name,
        star_rating=candidate.star_rating,
        approach_rate=candidate.approach_rate,
        bpm=candidate.bpm,
        support_count=evidence.collaborative.support_count,
        best_supporting_player_rank=(
            evidence.collaborative.best_supporting_player_rank
        ),
        attributes_within_iqr_count=evidence.attributes_within_iqr_count,
        why_recommended=_explanation(evidence),
    )


def _explanation(evidence: CandidatePreferenceEvidence) -> str:
    count = evidence.collaborative.support_count
    noun = "player" if count == 1 else "players"
    parts = [f"Recommended by {count} similar {noun}."]
    matching = [
        label
        for label, item in (
            ("star rating", evidence.star_rating),
            ("AR", evidence.approach_rate),
            ("BPM", evidence.bpm),
        )
        if item.within_target_iqr is True
    ]
    if matching:
        parts.append(f"{_join_labels(matching)} within your usual range.")
    return " ".join(parts)


def _join_labels(labels: Sequence[str]) -> str:
    first = labels[0][0].upper() + labels[0][1:]
    if len(labels) == 1:
        return first + " is"
    if len(labels) == 2:
        return f"{first} and {labels[1]} are"
    return f"{first}, {labels[1]}, and {labels[2]} are"


def _beatmap_id(item: PreferenceRankedCandidate) -> int:
    return item.preference_evidence.collaborative.candidate_map.beatmap_id


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Recommendation limit must be an integer from 1 through 100.")

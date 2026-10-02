"""Application-facing recommendation generation using the frozen MVP policy."""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from backend.app.analysis.statistics import TopPlayStatisticsInput
from backend.app.database.persistence import persist_user_top_plays
from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
    OsuTopPlay,
    OsuUserProfile,
)
from backend.app.recommendation.candidate_map_ranking import rank_candidate_map_evidence
from backend.app.recommendation.candidate_maps import CandidateMapSupport, extract_candidate_maps
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    NumericPreferenceSummary,
    TargetPreferenceProfile,
    annotate_candidate_evidence,
    build_target_preference_profile,
    calculate_numeric_summary,
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
class SupportingPlayer:
    user_id: int
    username: str | None
    similarity_rank: int
    mods: tuple[str, ...]


@dataclass(frozen=True)
class Recommendation:
    rank: int
    beatmap_id: int
    artist: str | None
    title: str | None
    difficulty_name: str | None
    beatmapset_id: int | None
    cover_url: str | None
    star_rating: float | None
    adjusted_star_rating: float | None
    approach_rate: float | None
    bpm: float | None
    suggested_mods: tuple[str, ...]
    support_count: int
    supporting_players: tuple[SupportingPlayer, ...]
    best_supporting_player_rank: int
    attributes_within_iqr_count: int
    why_recommended: str


@dataclass(frozen=True)
class RecommendationRequestAccounting:
    profile_requests: int
    target_top_play_requests: int
    leaderboard_requests: int
    candidate_top_play_requests: int
    beatmap_attribute_requests: int


@dataclass(frozen=True)
class PreferenceBounds:
    first_quartile: float
    median: float
    third_quartile: float


@dataclass(frozen=True)
class RecommendationPreferences:
    star_rating: PreferenceBounds | None
    approach_rate: PreferenceBounds | None
    bpm: PreferenceBounds | None


@dataclass(frozen=True)
class TargetModCombination:
    mods: tuple[str, ...]
    count: int
    share: float


@dataclass(frozen=True)
class TargetRecommendationProfile:
    primary_mods: tuple[str, ...]
    mod_distribution: tuple[TargetModCombination, ...]
    performance_points: PreferenceBounds | None
    actual_play_star_rating: PreferenceBounds | None


@dataclass(frozen=True)
class SimilarPlayerDiagnostic:
    similarity_rank: int
    username: str | None
    independent_overlap: int
    dominant_mods: tuple[str, ...]
    target_primary_mod_share: float
    performance_points: PreferenceBounds | None


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
    preferences: RecommendationPreferences
    target_profile: TargetRecommendationProfile
    similar_players: tuple[SimilarPlayerDiagnostic, ...]


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
    target_profile = _target_recommendation_profile(target)
    ranking = await ranking_function(
        target.profile.username,
        seed_count=SEED_COUNT,
        hydration_budget=HYDRATION_BUDGET,
        top_plays=CANDIDATE_TOP_PLAYS,
        osu_client=client,
    )
    ordered = build_hybrid_ranking(ranking, profile)
    returned = ordered[:limit]
    adjusted_stars, attribute_requests = await enrich_adjusted_stars(
        returned, target_profile.primary_mods, client
    )
    recommendations = tuple(
        _to_recommendation(
            item,
            adjusted_stars.get(_beatmap_id(item)),
            target_profile.primary_mods,
        )
        for item in returned
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
            beatmap_attribute_requests=attribute_requests,
        ),
        preferences=RecommendationPreferences(
            None,
            _preferences(profile).approach_rate,
            _preferences(profile).bpm,
        ),
        target_profile=target_profile,
        similar_players=_similar_player_diagnostics(
            ranking, target_profile.primary_mods
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


async def enrich_adjusted_stars(
    candidates: Sequence[PreferenceRankedCandidate],
    target_mods: tuple[str, ...],
    client: OsuApiClient,
) -> tuple[dict[int, float | None], int]:
    """Enrich only returned modded maps, retaining failures as missing display data."""
    semaphore = asyncio.Semaphore(5)
    requests: dict[tuple[int, tuple[str, ...]], asyncio.Task[float | None]] = {}

    async def fetch(beatmap_id: int, mods: tuple[str, ...]) -> float | None:
        async with semaphore:
            try:
                result = await client.get_beatmap_difficulty_attributes(
                    beatmap_id, mods
                )
            except OsuAuthenticationError:
                raise
            except (OsuNetworkError, OsuApiError):
                return None
            return result.star_rating

    base_by_id: dict[int, float | None] = {}
    for item in candidates:
        candidate = item.preference_evidence.collaborative.candidate_map
        base_by_id[candidate.beatmap_id] = candidate.star_rating
        if target_mods:
            key = (candidate.beatmap_id, target_mods)
            if key not in requests:
                requests[key] = asyncio.create_task(fetch(*key))

    fetched = await asyncio.gather(*requests.values()) if requests else ()
    values = dict(zip(requests, fetched, strict=True))
    adjusted = {
        beatmap_id: (
            base_by_id[beatmap_id]
            if not target_mods
            else values.get((beatmap_id, target_mods))
        )
        for beatmap_id in base_by_id
    }
    return adjusted, len(requests)


def suggested_mod_combination(
    supports: Sequence[CandidateMapSupport],
) -> tuple[str, ...]:
    """Select mode, then best supporter rank, then acronym tuple."""
    typed = tuple(supports)
    counts = Counter(support.mods for support in typed)
    best_ranks = {
        mods: min(
            support.similar_player_rank
            for support in typed
            if support.mods == mods
        )
        for mods in counts
    }
    return min(counts, key=lambda mods: (-counts[mods], best_ranks[mods], mods))


def _to_recommendation(
    item: PreferenceRankedCandidate,
    adjusted_star_rating: float | None,
    target_mods: tuple[str, ...],
) -> Recommendation:
    evidence = item.preference_evidence
    candidate = evidence.collaborative.candidate_map
    supporting_players = _supporting_players(candidate.supports)
    if len(supporting_players) != evidence.collaborative.support_count:
        raise ValueError("Recommendation support evidence contains duplicate users.")
    return Recommendation(
        rank=item.preference_rank,
        beatmap_id=candidate.beatmap_id,
        artist=candidate.artist,
        title=candidate.title,
        difficulty_name=candidate.difficulty_name,
        beatmapset_id=candidate.beatmapset_id,
        cover_url=(
            f"https://assets.ppy.sh/beatmaps/{candidate.beatmapset_id}/covers/cover.jpg"
            if candidate.beatmapset_id is not None
            else None
        ),
        star_rating=candidate.star_rating,
        adjusted_star_rating=adjusted_star_rating,
        approach_rate=candidate.approach_rate,
        bpm=candidate.bpm,
        suggested_mods=target_mods,
        support_count=evidence.collaborative.support_count,
        supporting_players=supporting_players,
        best_supporting_player_rank=(
            evidence.collaborative.best_supporting_player_rank
        ),
        attributes_within_iqr_count=evidence.attributes_within_iqr_count,
        why_recommended=_explanation(evidence),
    )


def _supporting_players(
    supports: Sequence[CandidateMapSupport],
) -> tuple[SupportingPlayer, ...]:
    """Expose the exact eligible support set in stable similarity order."""
    by_user: dict[int, CandidateMapSupport] = {}
    for support in supports:
        current = by_user.get(support.user_id)
        if current is None or support.similar_player_rank < current.similar_player_rank:
            by_user[support.user_id] = support
    return tuple(
        SupportingPlayer(
            user_id=support.user_id,
            username=support.username,
            similarity_rank=support.similar_player_rank,
            mods=support.mods,
        )
        for support in sorted(
            by_user.values(),
            key=lambda item: (item.similar_player_rank, item.user_id),
        )
    )


def _explanation(evidence: CandidatePreferenceEvidence) -> str:
    count = evidence.collaborative.support_count
    noun = "player" if count == 1 else "players"
    parts = [f"Recommended by {count} similar {noun}."]
    matching = [
        label
        for label, item in (
            ("base AR", evidence.approach_rate),
            ("base BPM", evidence.bpm),
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


def _preferences(profile: TargetPreferenceProfile) -> RecommendationPreferences:
    def bounds(value: NumericPreferenceSummary | None) -> PreferenceBounds | None:
        if value is None:
            return None
        return PreferenceBounds(
            value.first_quartile, value.median, value.third_quartile
        )

    return RecommendationPreferences(
        bounds(profile.star_rating), bounds(profile.approach_rate), bounds(profile.bpm)
    )


def _target_recommendation_profile(
    target: RefreshedTarget,
) -> TargetRecommendationProfile:
    counts = Counter(play.mods for play in target.top_plays)
    total = len(target.top_plays)
    distribution = tuple(
        TargetModCombination(mods, count, count / total if total else 0.0)
        for mods, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    primary = distribution[0].mods if distribution else ()
    pp = calculate_numeric_summary(play.performance_points for play in target.top_plays)
    return TargetRecommendationProfile(
        primary_mods=primary,
        mod_distribution=distribution,
        performance_points=(
            None if pp is None else PreferenceBounds(pp.first_quartile, pp.median, pp.third_quartile)
        ),
        # The top-play response exposes base beatmap difficulty, not played-mod difficulty.
        # Avoid up to 100 extra requests and leave the adjusted distribution unavailable.
        actual_play_star_rating=None,
    )


def _similar_player_diagnostics(
    ranking: RankedCandidateExperimentResult,
    target_mods: tuple[str, ...],
) -> tuple[SimilarPlayerDiagnostic, ...]:
    diagnostics: list[SimilarPlayerDiagnostic] = []
    for rank, player in enumerate(ranking.candidates[:RANKING_PLAYER_LIMIT], start=1):
        counts = Counter(play.mods for play in player.hydrated_top_plays)
        dominant = min(counts, key=lambda mods: (-counts[mods], mods)) if counts else ()
        total = len(player.hydrated_top_plays)
        pp = calculate_numeric_summary(
            play.performance_points for play in player.hydrated_top_plays
        )
        diagnostics.append(
            SimilarPlayerDiagnostic(
                similarity_rank=rank,
                username=player.username,
                independent_overlap=player.seed_excluded_shared_beatmap_count,
                dominant_mods=dominant,
                target_primary_mod_share=(counts[target_mods] / total if total else 0.0),
                performance_points=(
                    None if pp is None else PreferenceBounds(pp.first_quartile, pp.median, pp.third_quartile)
                ),
            )
        )
    return tuple(diagnostics)


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Recommendation limit must be an integer from 1 through 100.")

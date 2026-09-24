"""Describe target preferences alongside unchanged candidate-map ranking."""

from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from statistics import fmean, median

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.analysis.statistics import (
    ModAcronymCount,
    ModCombinationCount,
    TopPlayStatisticsInput,
    calculate_player_statistics,
)
from backend.app.database.connection import get_session_factory
from backend.app.database.models import Beatmap, User, UserTopPlay
from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.candidate_map_ranking import (
    CandidateMapEvidence,
    CandidateMapRankingExperimentResult,
    evaluate_candidate_map_ranking,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)

RankingFunction = Callable[..., Awaitable[CandidateMapRankingExperimentResult]]


@dataclass(frozen=True)
class NumericPreferenceSummary:
    count: int
    minimum: float
    first_quartile: float
    median: float
    third_quartile: float
    maximum: float
    mean: float


@dataclass(frozen=True)
class TargetPreferenceProfile:
    user_id: int
    username: str
    top_play_count: int
    star_rating: NumericPreferenceSummary | None
    approach_rate: NumericPreferenceSummary | None
    bpm: NumericPreferenceSummary | None
    exact_mod_combinations: tuple[ModCombinationCount, ...]
    individual_mods: tuple[ModAcronymCount, ...]
    top_exact_mod_combination: tuple[str, ...] | None


@dataclass(frozen=True)
class NumericCandidateEvidence:
    value: float | None
    delta_from_target_median: float | None
    within_target_iqr: bool | None


@dataclass(frozen=True)
class CandidatePreferenceEvidence:
    collaborative: CandidateMapEvidence
    star_rating: NumericCandidateEvidence
    approach_rate: NumericCandidateEvidence
    bpm: NumericCandidateEvidence
    attributes_within_iqr_count: int
    comparable_attribute_count: int
    exact_supporting_mod_combinations: tuple[ModCombinationCount, ...]
    individual_supporting_mods: tuple[ModAcronymCount, ...]
    supports_using_target_top_mod_combo: int | None


@dataclass(frozen=True)
class PreferencePoolSummary:
    candidate_map_count: int
    star_metadata_count: int
    star_metadata_missing_count: int
    star_within_iqr_count: int
    ar_metadata_count: int
    ar_metadata_missing_count: int
    ar_within_iqr_count: int
    bpm_metadata_count: int
    bpm_metadata_missing_count: int
    bpm_within_iqr_count: int
    within_all_available_target_iqrs_count: int
    iqr_count_distribution: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class PreferenceEvidenceExperimentResult:
    target_profile: TargetPreferenceProfile
    ranking: CandidateMapRankingExperimentResult
    candidates: tuple[CandidatePreferenceEvidence, ...]
    whole_pool_summary: PreferencePoolSummary
    displayed_prefix_summary: PreferencePoolSummary
    show_maps: int
    additional_preference_requests: int


def calculate_numeric_summary(
    values: Iterable[float | None],
) -> NumericPreferenceSummary | None:
    """Use linear interpolation at index ``(n - 1) * percentile``."""
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    return NumericPreferenceSummary(
        count=len(ordered),
        minimum=ordered[0],
        first_quartile=_percentile(ordered, 0.25),
        median=float(median(ordered)),
        third_quartile=_percentile(ordered, 0.75),
        maximum=ordered[-1],
        mean=fmean(ordered),
    )


def compare_numeric_evidence(
    value: float | None,
    target: NumericPreferenceSummary | None,
) -> NumericCandidateEvidence:
    if value is None or target is None:
        return NumericCandidateEvidence(value, None, None)
    return NumericCandidateEvidence(
        value=value,
        delta_from_target_median=abs(value - target.median),
        within_target_iqr=(target.first_quartile <= value <= target.third_quartile),
    )


def annotate_candidate_maps(
    ranking: CandidateMapRankingExperimentResult,
    target_profile: TargetPreferenceProfile,
) -> tuple[CandidatePreferenceEvidence, ...]:
    """Annotate candidates in the exact existing T0027 order."""
    return annotate_candidate_evidence(
        ranking.evidence_aware_ordering, target_profile
    )


def annotate_candidate_evidence(
    candidates: Sequence[CandidateMapEvidence],
    target_profile: TargetPreferenceProfile,
) -> tuple[CandidatePreferenceEvidence, ...]:
    """Apply existing T0028 evidence semantics to an explicit candidate set."""
    annotated: list[CandidatePreferenceEvidence] = []
    for collaborative in candidates:
        candidate_map = collaborative.candidate_map
        stars = compare_numeric_evidence(
            candidate_map.star_rating, target_profile.star_rating
        )
        ar = compare_numeric_evidence(
            candidate_map.approach_rate, target_profile.approach_rate
        )
        bpm = compare_numeric_evidence(candidate_map.bpm, target_profile.bpm)
        exact_mods, individual_mods = summarize_mods(
            support.mods for support in candidate_map.supports
        )
        top_combo = target_profile.top_exact_mod_combination
        annotated.append(
            CandidatePreferenceEvidence(
                collaborative=collaborative,
                star_rating=stars,
                approach_rate=ar,
                bpm=bpm,
                attributes_within_iqr_count=sum(
                    item.within_target_iqr is True for item in (stars, ar, bpm)
                ),
                comparable_attribute_count=sum(
                    item.within_target_iqr is not None for item in (stars, ar, bpm)
                ),
                exact_supporting_mod_combinations=exact_mods,
                individual_supporting_mods=individual_mods,
                supports_using_target_top_mod_combo=(
                    None
                    if top_combo is None
                    else sum(
                        support.mods == top_combo
                        for support in candidate_map.supports
                    )
                ),
            )
        )
    return tuple(annotated)


def build_target_preference_profile(
    user_id: int,
    username: str,
    plays: Sequence[TopPlayStatisticsInput],
) -> TargetPreferenceProfile:
    """Build the existing T0028 profile from explicitly supplied play evidence."""
    if not plays:
        raise TargetTopPlaysEmptyError(
            "The target has no top plays from which to build a preference profile."
        )
    existing = calculate_player_statistics(user_id, username, plays)
    return TargetPreferenceProfile(
        user_id=user_id,
        username=username,
        top_play_count=len(plays),
        star_rating=calculate_numeric_summary(item.star_rating for item in plays),
        approach_rate=calculate_numeric_summary(
            item.approach_rate for item in plays
        ),
        bpm=calculate_numeric_summary(item.bpm for item in plays),
        exact_mod_combinations=existing.exact_mod_combinations,
        individual_mods=existing.individual_mods,
        top_exact_mod_combination=(
            existing.exact_mod_combinations[0].mods
            if existing.exact_mod_combinations
            else None
        ),
    )


def summarize_mods(
    combinations: Iterable[tuple[str, ...]],
) -> tuple[tuple[ModCombinationCount, ...], tuple[ModAcronymCount, ...]]:
    exact: Counter[tuple[str, ...]] = Counter(combinations)
    individual: Counter[str] = Counter()
    for mods, count in exact.items():
        for mod in mods:
            individual[mod] += count
    exact_counts = tuple(
        ModCombinationCount(mods=mods, count=count)
        for mods, count in sorted(exact.items(), key=lambda item: (-item[1], item[0]))
    )
    individual_counts = tuple(
        ModAcronymCount(acronym=mod, count=count)
        for mod, count in sorted(
            individual.items(), key=lambda item: (-item[1], item[0])
        )
    )
    return exact_counts, individual_counts


def summarize_preference_pool(
    candidates: Sequence[CandidatePreferenceEvidence],
    target_profile: TargetPreferenceProfile,
) -> PreferencePoolSummary:
    stars = [candidate.star_rating for candidate in candidates]
    ars = [candidate.approach_rate for candidate in candidates]
    bpms = [candidate.bpm for candidate in candidates]
    target_available_count = sum(
        summary is not None
        for summary in (
            target_profile.star_rating,
            target_profile.approach_rate,
            target_profile.bpm,
        )
    )
    distribution = Counter(
        candidate.attributes_within_iqr_count for candidate in candidates
    )
    return PreferencePoolSummary(
        candidate_map_count=len(candidates),
        star_metadata_count=sum(item.value is not None for item in stars),
        star_metadata_missing_count=sum(item.value is None for item in stars),
        star_within_iqr_count=sum(item.within_target_iqr is True for item in stars),
        ar_metadata_count=sum(item.value is not None for item in ars),
        ar_metadata_missing_count=sum(item.value is None for item in ars),
        ar_within_iqr_count=sum(item.within_target_iqr is True for item in ars),
        bpm_metadata_count=sum(item.value is not None for item in bpms),
        bpm_metadata_missing_count=sum(item.value is None for item in bpms),
        bpm_within_iqr_count=sum(item.within_target_iqr is True for item in bpms),
        within_all_available_target_iqrs_count=sum(
            target_available_count > 0
            and candidate.comparable_attribute_count == target_available_count
            and candidate.attributes_within_iqr_count == target_available_count
            for candidate in candidates
        ),
        iqr_count_distribution=tuple(
            (count, distribution.get(count, 0)) for count in range(4)
        ),
    )


async def evaluate_preference_evidence(
    username: str,
    *,
    seed_count: int = 5,
    hydration_budget: int = 25,
    top_plays: int = 100,
    similar_player_limit: int = 10,
    show_maps: int = 30,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    ranking_function: RankingFunction = evaluate_candidate_map_ranking,
    osu_client: OsuApiClient | None = None,
) -> PreferenceEvidenceExperimentResult:
    _validate_bound(show_maps, 1, 100, "Show-maps limit")
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    profile = _load_target_profile(
        requested_username,
        top_plays,
        session_factory or get_session_factory(),
    )
    arguments: dict[str, object] = {
        "seed_count": seed_count,
        "hydration_budget": hydration_budget,
        "top_plays": top_plays,
        "similar_player_limit": similar_player_limit,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    ranking = await ranking_function(requested_username, **arguments)
    candidates = annotate_candidate_maps(ranking, profile)
    return PreferenceEvidenceExperimentResult(
        target_profile=profile,
        ranking=ranking,
        candidates=candidates,
        whole_pool_summary=summarize_preference_pool(candidates, profile),
        displayed_prefix_summary=summarize_preference_pool(
            candidates[:show_maps], profile
        ),
        show_maps=show_maps,
        additional_preference_requests=0,
    )


def _load_target_profile(
    username: str,
    top_plays: int,
    session_factory: Callable[[], Session] | sessionmaker[Session],
) -> TargetPreferenceProfile:
    _validate_bound(top_plays, 1, 100, "Top-play limit")
    with session_factory() as session:
        target = session.execute(
            select(User.user_id, User.username).where(
                func.lower(User.username) == username.lower()
            )
        ).one_or_none()
        if target is None:
            raise SimilarityTargetNotFoundError(
                f"Persisted user '{username}' was not found."
            )
        rows = session.execute(
            select(
                Beatmap.star_rating,
                Beatmap.approach_rate,
                Beatmap.bpm,
                UserTopPlay.mods,
            )
            .join(Beatmap, Beatmap.beatmap_id == UserTopPlay.beatmap_id)
            .where(UserTopPlay.user_id == target.user_id)
            .order_by(UserTopPlay.position)
            .limit(top_plays)
        ).all()
    if not rows:
        raise TargetTopPlaysEmptyError(
            "The persisted target has no top plays to analyze."
        )
    inputs = tuple(
        TopPlayStatisticsInput(
            performance_points=None,
            accuracy=None,
            star_rating=row.star_rating,
            approach_rate=row.approach_rate,
            bpm=row.bpm,
            mods=tuple(row.mods),
        )
        for row in rows
    )
    return build_target_preference_profile(
        target.user_id, target.username, inputs
    )


def _percentile(ordered: Sequence[float], percentile: float) -> float:
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _validate_bound(value: int, minimum: int, maximum: int, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}."
        )

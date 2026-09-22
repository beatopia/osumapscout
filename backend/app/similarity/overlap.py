"""Simple top-play beatmap-overlap similarity experiment."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.candidates.hydration import (
    CandidateHydrationResult,
    hydrate_candidate_top_plays,
)
from backend.app.database.connection import get_session_factory
from backend.app.database.models import User, UserTopPlay

HydrationFunction = Callable[..., Awaitable[CandidateHydrationResult]]


class SimilarityTargetNotFoundError(LookupError):
    """Raised when no persisted target matches the requested username."""


class TargetTopPlaysEmptyError(RuntimeError):
    """Raised when the target has no persisted evidence to compare."""


@dataclass(frozen=True)
class OverlapMetrics:
    """Pure set-overlap metrics for two beatmap-ID collections."""

    target_play_count: int
    candidate_play_count: int
    shared_beatmap_count: int
    jaccard_similarity: float
    target_coverage: float


@dataclass(frozen=True)
class CandidateSimilarity:
    """One candidate's experimental top-play overlap with the target."""

    user_id: int
    username: str | None
    sources: tuple[str, ...]
    target_play_count: int
    candidate_play_count: int
    shared_beatmap_count: int
    jaccard_similarity: float
    target_coverage: float


@dataclass(frozen=True)
class SimilarityExperimentResult:
    """Ephemeral overlap results and inherited upstream request counts."""

    target_user_id: int
    target_username: str
    target_play_count: int
    candidates: tuple[CandidateSimilarity, ...]
    ranking_requests_made: int
    top_play_requests_made: int


def calculate_overlap_similarity(
    target_beatmap_ids: Iterable[int],
    candidate_beatmap_ids: Iterable[int],
) -> OverlapMetrics:
    """Calculate unweighted metrics from unique beatmap IDs only."""
    target_set = frozenset(target_beatmap_ids)
    if not target_set:
        raise TargetTopPlaysEmptyError(
            "The persisted target has no top plays to compare."
        )

    candidate_set = frozenset(candidate_beatmap_ids)
    shared_count = len(target_set & candidate_set)
    union_count = len(target_set | candidate_set)

    return OverlapMetrics(
        target_play_count=len(target_set),
        candidate_play_count=len(candidate_set),
        shared_beatmap_count=shared_count,
        jaccard_similarity=shared_count / union_count,
        target_coverage=shared_count / len(target_set),
    )


async def run_overlap_similarity_experiment(
    username: str,
    *,
    candidate_pool_limit: int = 20,
    hydrate_limit: int = 5,
    comparison_top_plays: int = 100,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    hydration_function: HydrationFunction = hydrate_candidate_top_plays,
) -> SimilarityExperimentResult:
    """Compare persisted target evidence with one bounded hydration result."""
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_comparison_depth(comparison_top_plays)

    create_session = session_factory or get_session_factory()
    with create_session() as session:
        target = session.execute(
            select(User.user_id, User.username).where(
                func.lower(User.username) == requested_username.lower()
            )
        ).one_or_none()
        if target is None:
            raise SimilarityTargetNotFoundError(
                f"Persisted user '{requested_username}' was not found."
            )

        target_rows = session.execute(
            select(UserTopPlay.beatmap_id)
            .where(UserTopPlay.user_id == target.user_id)
            .order_by(UserTopPlay.position)
            .limit(comparison_top_plays)
        ).all()

    target_beatmap_ids = tuple(
        row.beatmap_id for row in target_rows[:comparison_top_plays]
    )
    if not target_beatmap_ids:
        raise TargetTopPlaysEmptyError(
            "The persisted target has no top plays to compare."
        )

    hydration = await hydration_function(
        requested_username,
        candidate_pool_limit=candidate_pool_limit,
        hydrate_limit=hydrate_limit,
        top_plays_per_candidate=comparison_top_plays,
    )

    candidate_results: list[CandidateSimilarity] = []
    for candidate in hydration.hydrated_candidates:
        metrics = calculate_overlap_similarity(
            target_beatmap_ids,
            (
                play.beatmap_id
                for play in candidate.top_plays[:comparison_top_plays]
            ),
        )
        candidate_results.append(
            CandidateSimilarity(
                user_id=candidate.user_id,
                username=candidate.username,
                sources=candidate.sources,
                target_play_count=metrics.target_play_count,
                candidate_play_count=metrics.candidate_play_count,
                shared_beatmap_count=metrics.shared_beatmap_count,
                jaccard_similarity=metrics.jaccard_similarity,
                target_coverage=metrics.target_coverage,
            )
        )

    candidate_results.sort(
        key=lambda candidate: (
            -candidate.shared_beatmap_count,
            -candidate.jaccard_similarity,
            -candidate.target_coverage,
            candidate.user_id,
        )
    )

    return SimilarityExperimentResult(
        target_user_id=target.user_id,
        target_username=target.username,
        target_play_count=len(frozenset(target_beatmap_ids)),
        candidates=tuple(candidate_results),
        ranking_requests_made=hydration.ranking_requests_made,
        top_play_requests_made=hydration.top_play_requests_made,
    )


def _validate_comparison_depth(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 100
    ):
        raise ValueError(
            "Comparison top-play limit must be an integer from 1 through 100."
        )

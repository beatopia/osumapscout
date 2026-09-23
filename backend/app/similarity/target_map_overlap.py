"""Evaluate target-map candidates with raw and seed-excluded overlap."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidateExperiment,
    TargetMapSeed,
    discover_target_map_candidates,
)
from backend.app.database.connection import get_session_factory
from backend.app.database.models import User, UserTopPlay
from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
)
from backend.app.similarity.overlap import (
    OverlapMetrics,
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
    calculate_overlap_similarity,
)

AcquisitionFunction = Callable[..., Awaitable[TargetMapCandidateExperiment]]


class SeedExcludedTargetEmptyError(RuntimeError):
    """Raised when removing selected seeds leaves no target evidence."""


@dataclass(frozen=True)
class RawAndSeedExcludedMetrics:
    """The existing overlap metrics before and after seed removal."""

    raw: OverlapMetrics
    seed_excluded: OverlapMetrics


@dataclass(frozen=True)
class TargetMapCandidateOverlap:
    """Acquisition evidence and independent overlap for one candidate."""

    user_id: int
    username: str | None
    seed_beatmap_ids: tuple[int, ...]
    candidate_play_count: int
    raw_shared_beatmap_count: int
    raw_jaccard_similarity: float
    raw_target_coverage: float
    seed_excluded_shared_beatmap_count: int
    seed_excluded_jaccard_similarity: float
    seed_excluded_target_coverage: float

    @property
    def seed_hit_count(self) -> int:
        return len(self.seed_beatmap_ids)


@dataclass(frozen=True)
class TargetMapOverlapExperimentResult:
    """Ephemeral evaluation result with bounded request accounting."""

    target_user_id: int
    target_username: str
    target_play_count: int
    selected_seeds: tuple[TargetMapSeed, ...]
    discovered_candidate_count: int
    candidates: tuple[TargetMapCandidateOverlap, ...]
    leaderboard_requests_made: int
    top_play_requests_made: int


def calculate_raw_and_seed_excluded_overlap(
    target_beatmap_ids: Iterable[int],
    candidate_beatmap_ids: Iterable[int],
    seed_beatmap_ids: Iterable[int],
) -> RawAndSeedExcludedMetrics:
    """Reuse T0020 metrics with only selected seed IDs removed."""
    target_set = frozenset(target_beatmap_ids)
    candidate_set = frozenset(candidate_beatmap_ids)
    seed_set = frozenset(seed_beatmap_ids)

    raw = calculate_overlap_similarity(target_set, candidate_set)
    seed_excluded_target = target_set - seed_set
    if not seed_excluded_target:
        raise SeedExcludedTargetEmptyError(
            "Removing selected seed maps leaves no target top plays to compare."
        )
    seed_excluded = calculate_overlap_similarity(
        seed_excluded_target,
        candidate_set - seed_set,
    )
    return RawAndSeedExcludedMetrics(raw=raw, seed_excluded=seed_excluded)


async def evaluate_target_map_candidates(
    username: str,
    *,
    seed_count: int = 5,
    candidate_limit: int = 30,
    hydrate_limit: int = 10,
    top_plays: int = 100,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    acquisition_function: AcquisitionFunction = discover_target_map_candidates,
    osu_client: OsuApiClient | None = None,
) -> TargetMapOverlapExperimentResult:
    """Acquire, sequentially hydrate, and evaluate target-map candidates."""
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_bound(seed_count, 1, 10, "Seed count")
    _validate_bound(candidate_limit, 1, 100, "Candidate limit")
    _validate_bound(hydrate_limit, 1, 20, "Hydrate limit")
    _validate_bound(top_plays, 1, 100, "Top-play limit")

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
        rows = session.execute(
            select(UserTopPlay.beatmap_id)
            .where(UserTopPlay.user_id == target.user_id)
            .order_by(UserTopPlay.position)
            .limit(top_plays)
        ).all()

    target_beatmap_ids = tuple(row.beatmap_id for row in rows[:top_plays])
    if not target_beatmap_ids:
        raise TargetTopPlaysEmptyError(
            "The persisted target has no top plays to compare."
        )

    acquisition_arguments: dict[str, object] = {
        "seed_count": seed_count,
        "candidate_limit": candidate_limit,
    }
    if osu_client is not None:
        acquisition_arguments["osu_client"] = osu_client
    acquisition = await acquisition_function(
        requested_username,
        **acquisition_arguments,
    )

    seed_ids = tuple(seed.beatmap_id for seed in acquisition.selected_seeds)
    if not frozenset(target_beatmap_ids) - frozenset(seed_ids):
        raise SeedExcludedTargetEmptyError(
            "Removing selected seed maps leaves no target top plays to compare."
        )

    selected_candidates = acquisition.candidates[:hydrate_limit]
    client = osu_client
    if selected_candidates and client is None:
        client = OsuApiClient(OsuCredentials.from_environment())

    evaluated: list[TargetMapCandidateOverlap] = []
    top_play_requests_made = 0
    for candidate in selected_candidates:
        assert client is not None
        try:
            candidate_plays = await client.get_top_plays_by_user_id(
                candidate.user_id,
                limit=top_plays,
            )
        except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
            raise CandidateHydrationError(
                f"Could not hydrate top plays for candidate user {candidate.user_id}."
            ) from error
        top_play_requests_made += 1

        metrics = calculate_raw_and_seed_excluded_overlap(
            target_beatmap_ids,
            (play.beatmap_id for play in candidate_plays[:top_plays]),
            seed_ids,
        )
        evaluated.append(
            TargetMapCandidateOverlap(
                user_id=candidate.user_id,
                username=candidate.username,
                seed_beatmap_ids=candidate.seed_beatmap_ids,
                candidate_play_count=metrics.raw.candidate_play_count,
                raw_shared_beatmap_count=metrics.raw.shared_beatmap_count,
                raw_jaccard_similarity=metrics.raw.jaccard_similarity,
                raw_target_coverage=metrics.raw.target_coverage,
                seed_excluded_shared_beatmap_count=(
                    metrics.seed_excluded.shared_beatmap_count
                ),
                seed_excluded_jaccard_similarity=(
                    metrics.seed_excluded.jaccard_similarity
                ),
                seed_excluded_target_coverage=(
                    metrics.seed_excluded.target_coverage
                ),
            )
        )

    evaluated.sort(
        key=lambda candidate: (
            -candidate.seed_excluded_shared_beatmap_count,
            -candidate.seed_excluded_jaccard_similarity,
            -candidate.seed_hit_count,
            candidate.user_id,
        )
    )
    return TargetMapOverlapExperimentResult(
        target_user_id=target.user_id,
        target_username=target.username,
        target_play_count=len(frozenset(target_beatmap_ids)),
        selected_seeds=acquisition.selected_seeds,
        discovered_candidate_count=acquisition.unique_candidate_count,
        candidates=tuple(evaluated),
        leaderboard_requests_made=acquisition.leaderboard_requests_made,
        top_play_requests_made=top_play_requests_made,
    )


def _validate_bound(value: int, minimum: int, maximum: int, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}."
        )

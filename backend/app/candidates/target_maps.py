"""Experimental candidate acquisition from target-map leaderboards."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database.connection import get_session_factory
from backend.app.database.models import User, UserTopPlay
from backend.app.osu.client import OsuApiClient, OsuCredentials

DEFAULT_SEED_COUNT = 5
DEFAULT_CANDIDATE_LIMIT = 50


class TargetMapCandidateTargetNotFoundError(LookupError):
    """Raised when the persisted target does not exist."""


class TargetMapEvidenceEmptyError(RuntimeError):
    """Raised when the persisted target has no seedable top plays."""


@dataclass(frozen=True)
class TargetMapSeed:
    """One persisted top-play position selected as a leaderboard seed."""

    position: int
    beatmap_id: int


@dataclass(frozen=True)
class TargetMapCandidate:
    """One unique leaderboard candidate and its seed-map provenance."""

    user_id: int
    username: str | None
    seed_beatmap_ids: tuple[int, ...]

    @property
    def seed_hit_count(self) -> int:
        return len(self.seed_beatmap_ids)


@dataclass(frozen=True)
class TargetMapCandidateExperiment:
    """Complete ephemeral output from all selected seed leaderboards."""

    target_user_id: int
    target_username: str
    selected_seeds: tuple[TargetMapSeed, ...]
    candidates: tuple[TargetMapCandidate, ...]
    unique_candidate_count: int
    seed_hit_distribution: tuple[tuple[int, int], ...]
    leaderboard_requests_made: int


@dataclass
class _CandidateAccumulator:
    user_id: int
    username: str | None
    seed_beatmap_ids: list[int]
    first_discovery_order: int


def select_evenly_spaced_seeds(
    ordered_plays: Sequence[TargetMapSeed],
    seed_count: int,
) -> tuple[TargetMapSeed, ...]:
    """Select deterministic positions spread across available evidence."""
    _validate_bound(seed_count, 1, 10, "Seed count")
    if not ordered_plays:
        return ()

    selected_count = min(seed_count, len(ordered_plays))
    if selected_count == 1:
        return (ordered_plays[0],)

    last_index = len(ordered_plays) - 1
    indexes = (
        index * last_index // (selected_count - 1)
        for index in range(selected_count)
    )
    return tuple(ordered_plays[index] for index in indexes)


async def discover_target_map_candidates(
    username: str,
    *,
    seed_count: int = DEFAULT_SEED_COUNT,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    osu_client: OsuApiClient | None = None,
) -> TargetMapCandidateExperiment:
    """Acquire candidates from every selected target-map leaderboard."""
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_bound(seed_count, 1, 10, "Seed count")
    _validate_bound(candidate_limit, 1, 100, "Candidate limit")

    create_session = session_factory or get_session_factory()
    with create_session() as session:
        target = session.execute(
            select(User.user_id, User.username).where(
                func.lower(User.username) == requested_username.lower()
            )
        ).one_or_none()
        if target is None:
            raise TargetMapCandidateTargetNotFoundError(
                f"Persisted user '{requested_username}' was not found."
            )

        rows = session.execute(
            select(UserTopPlay.position, UserTopPlay.beatmap_id)
            .where(UserTopPlay.user_id == target.user_id)
            .order_by(UserTopPlay.position)
        ).all()

    ordered_plays = tuple(
        TargetMapSeed(position=row.position, beatmap_id=row.beatmap_id)
        for row in rows
    )
    if not ordered_plays:
        raise TargetMapEvidenceEmptyError(
            "The persisted target has no top plays to use as leaderboard seeds."
        )
    selected_seeds = select_evenly_spaced_seeds(ordered_plays, seed_count)

    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    accumulated: dict[int, _CandidateAccumulator] = {}
    leaderboard_requests_made = 0
    next_discovery_order = 0

    for seed in selected_seeds:
        leaderboard_users = await client.get_beatmap_leaderboard_users(
            seed.beatmap_id
        )
        leaderboard_requests_made += 1
        seen_on_seed: set[int] = set()
        for leaderboard_user in leaderboard_users:
            if (
                leaderboard_user.user_id == target.user_id
                or leaderboard_user.user_id in seen_on_seed
            ):
                continue
            seen_on_seed.add(leaderboard_user.user_id)

            existing = accumulated.get(leaderboard_user.user_id)
            if existing is None:
                accumulated[leaderboard_user.user_id] = _CandidateAccumulator(
                    user_id=leaderboard_user.user_id,
                    username=leaderboard_user.username,
                    seed_beatmap_ids=[seed.beatmap_id],
                    first_discovery_order=next_discovery_order,
                )
                next_discovery_order += 1
            else:
                existing.seed_beatmap_ids.append(seed.beatmap_id)
                if existing.username is None:
                    existing.username = leaderboard_user.username

    ordered_candidates = sorted(
        accumulated.values(),
        key=lambda candidate: (
            -len(candidate.seed_beatmap_ids),
            candidate.first_discovery_order,
            candidate.user_id,
        ),
    )
    candidates = tuple(
        TargetMapCandidate(
            user_id=candidate.user_id,
            username=candidate.username,
            seed_beatmap_ids=tuple(candidate.seed_beatmap_ids),
        )
        for candidate in ordered_candidates[:candidate_limit]
    )
    hit_counts: dict[int, int] = {}
    for candidate in ordered_candidates:
        hits = len(candidate.seed_beatmap_ids)
        hit_counts[hits] = hit_counts.get(hits, 0) + 1

    return TargetMapCandidateExperiment(
        target_user_id=target.user_id,
        target_username=target.username,
        selected_seeds=selected_seeds,
        candidates=candidates,
        unique_candidate_count=len(accumulated),
        seed_hit_distribution=tuple(
            sorted(hit_counts.items(), reverse=True)
        ),
        leaderboard_requests_made=leaderboard_requests_made,
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

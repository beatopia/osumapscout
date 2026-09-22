"""Read-only, bounded candidate-user discovery."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database.connection import get_session_factory
from backend.app.database.models import User
from backend.app.osu.client import OsuApiClient, OsuCredentials

MAX_CANDIDATES = 100
MAX_RANKING_REQUESTS = 3


class CandidateTargetNotFoundError(LookupError):
    """Raised when candidate discovery cannot find its persisted target."""


@dataclass(frozen=True)
class CandidateUser:
    """One unique candidate identity and its discovery provenance."""

    user_id: int
    username: str | None
    sources: tuple[str, ...]


@dataclass(frozen=True)
class CandidateDiscoveryResult:
    """Bounded output and upstream request accounting for one target."""

    target_user_id: int
    target_username: str
    requested_count: int
    candidates: tuple[CandidateUser, ...]
    ranking_requests_made: int


async def discover_candidate_users(
    username: str,
    limit: int = MAX_CANDIDATES,
    *,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    osu_client: OsuApiClient | None = None,
) -> CandidateDiscoveryResult:
    """Return local candidates first, then bounded ranking candidates."""
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_limit(limit)

    create_session = session_factory or get_session_factory()
    with create_session() as session:
        target = session.execute(
            select(User.user_id, User.username).where(
                func.lower(User.username) == requested_username.lower()
            )
        ).one_or_none()
        if target is None:
            raise CandidateTargetNotFoundError(
                f"Persisted user '{requested_username}' was not found."
            )

        local_rows = session.execute(
            select(User.user_id, User.username)
            .where(User.user_id != target.user_id)
            .order_by(User.user_id)
            .limit(limit)
        ).all()

    candidates = [
        CandidateUser(row.user_id, row.username, ("local",))
        for row in local_rows[:limit]
    ]
    positions_by_id = {
        candidate.user_id: position
        for position, candidate in enumerate(candidates)
    }
    if len(candidates) >= limit:
        return CandidateDiscoveryResult(
            target.user_id,
            target.username,
            limit,
            tuple(candidates),
            0,
        )

    client = osu_client
    if client is None:
        client = OsuApiClient(OsuCredentials.from_environment())

    cursor: tuple[tuple[str, str], ...] | None = None
    ranking_requests_made = 0
    while ranking_requests_made < MAX_RANKING_REQUESTS:
        page = await client.get_osu_performance_ranking(cursor)
        ranking_requests_made += 1

        for ranking_user in page.users:
            if ranking_user.user_id == target.user_id:
                continue

            existing_position = positions_by_id.get(ranking_user.user_id)
            if existing_position is not None:
                existing = candidates[existing_position]
                if "ranking" not in existing.sources:
                    candidates[existing_position] = CandidateUser(
                        user_id=existing.user_id,
                        username=existing.username or ranking_user.username,
                        sources=("local", "ranking"),
                    )
                continue

            candidates.append(
                CandidateUser(
                    user_id=ranking_user.user_id,
                    username=ranking_user.username,
                    sources=("ranking",),
                )
            )
            positions_by_id[ranking_user.user_id] = len(candidates) - 1
            if len(candidates) >= limit:
                break

        if len(candidates) >= limit or page.cursor is None:
            break
        cursor = page.cursor

    return CandidateDiscoveryResult(
        target.user_id,
        target.username,
        limit,
        tuple(candidates),
        ranking_requests_made,
    )


def _validate_limit(limit: int) -> None:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_CANDIDATES
    ):
        raise ValueError("Candidate limit must be an integer from 1 through 100.")

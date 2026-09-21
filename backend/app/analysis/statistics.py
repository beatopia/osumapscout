"""Descriptive statistics calculated from persisted current top plays."""

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from statistics import fmean

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database.connection import get_session_factory
from backend.app.database.models import Beatmap, User, UserTopPlay


class PlayerNotFoundError(LookupError):
    """Raised when no persisted user matches the requested username."""


@dataclass(frozen=True)
class ModCombinationCount:
    """Count for one exact stored mod combination."""

    mods: tuple[str, ...]
    count: int


@dataclass(frozen=True)
class ModAcronymCount:
    """Count for one individual mod acronym."""

    acronym: str
    count: int


@dataclass(frozen=True)
class PlayerStatistics:
    """Descriptive statistics for one persisted user's current top plays."""

    user_id: int
    username: str
    top_play_count: int
    average_pp: float | None
    average_accuracy: float | None
    average_star_rating: float | None
    average_approach_rate: float | None
    average_bpm: float | None
    exact_mod_combinations: tuple[ModCombinationCount, ...]
    individual_mods: tuple[ModAcronymCount, ...]


@dataclass(frozen=True)
class TopPlayStatisticsInput:
    """Persisted values needed to calculate statistics for one top play."""

    performance_points: float | None
    accuracy: float | None
    star_rating: float | None
    approach_rate: float | None
    bpm: float | None
    mods: tuple[str, ...]


def calculate_player_statistics(
    user_id: int,
    username: str,
    top_plays: Iterable[TopPlayStatisticsInput],
) -> PlayerStatistics:
    """Calculate null-aware statistics without performing database I/O."""
    plays = tuple(top_plays)
    exact_combinations: Counter[tuple[str, ...]] = Counter()
    individual_mods: Counter[str] = Counter()

    for play in plays:
        exact_combinations[play.mods] += 1
        individual_mods.update(play.mods)

    combination_counts = tuple(
        ModCombinationCount(mods=mods, count=count)
        for mods, count in sorted(
            exact_combinations.items(),
            key=lambda item: (-item[1], item[0]),
        )
    )
    acronym_counts = tuple(
        ModAcronymCount(acronym=acronym, count=count)
        for acronym, count in sorted(
            individual_mods.items(),
            key=lambda item: (-item[1], item[0]),
        )
    )

    return PlayerStatistics(
        user_id=user_id,
        username=username,
        top_play_count=len(plays),
        average_pp=_average(play.performance_points for play in plays),
        average_accuracy=_average(play.accuracy for play in plays),
        average_star_rating=_average(play.star_rating for play in plays),
        average_approach_rate=_average(play.approach_rate for play in plays),
        average_bpm=_average(play.bpm for play in plays),
        exact_mod_combinations=combination_counts,
        individual_mods=acronym_counts,
    )


def get_player_statistics(
    username: str,
    *,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
) -> PlayerStatistics:
    """Load one persisted user by username and calculate current statistics."""
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")

    create_session = session_factory or get_session_factory()
    with create_session() as session:
        user = session.scalar(
            select(User).where(
                func.lower(User.username) == requested_username.lower()
            )
        )
        if user is None:
            raise PlayerNotFoundError(
                f"Persisted user '{requested_username}' was not found."
            )

        rows = session.execute(
            select(
                UserTopPlay.performance_points,
                UserTopPlay.accuracy,
                Beatmap.star_rating,
                Beatmap.approach_rate,
                Beatmap.bpm,
                UserTopPlay.mods,
            )
            .join(Beatmap, Beatmap.beatmap_id == UserTopPlay.beatmap_id)
            .where(UserTopPlay.user_id == user.user_id)
            .order_by(UserTopPlay.position)
        ).all()

        plays = (
            TopPlayStatisticsInput(
                performance_points=row.performance_points,
                accuracy=row.accuracy,
                star_rating=row.star_rating,
                approach_rate=row.approach_rate,
                bpm=row.bpm,
                mods=tuple(row.mods),
            )
            for row in rows
        )
        return calculate_player_statistics(user.user_id, user.username, plays)


def _average(values: Iterable[float | None]) -> float | None:
    present_values = [value for value in values if value is not None]
    return fmean(present_values) if present_values else None

"""Transactional persistence for complete current osu! user state."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database.connection import get_session_factory
from backend.app.database.models import Beatmap, User, UserTopPlay
from backend.app.osu.client import OsuTopPlay, OsuUserProfile


@dataclass(frozen=True)
class PersistenceResult:
    """Concise result of one complete current-state refresh."""

    user_id: int
    username: str
    top_play_count: int
    beatmap_count: int


def parse_played_at(value: str | None) -> datetime | None:
    """Parse an osu! timestamp as a timezone-aware UTC datetime."""
    if value is None:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid played_at timestamp: {value!r}") from error

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("played_at must include a timezone offset.")

    return parsed.astimezone(timezone.utc)


def persist_user_top_plays(
    profile: OsuUserProfile,
    top_plays: Sequence[OsuTopPlay],
    *,
    fetched_at: datetime | None = None,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
) -> PersistenceResult:
    """Replace one user's complete current top-play state atomically."""
    observed_at = fetched_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware.")
    observed_at = observed_at.astimezone(timezone.utc)

    create_session = session_factory or get_session_factory()
    with create_session() as session:
        with session.begin():
            user = session.get(User, profile.user_id)
            if user is None:
                user = User(user_id=profile.user_id)
                session.add(user)

            user.username = profile.username
            user.country_code = profile.country_code
            user.avatar_url = profile.avatar_url
            user.global_rank = profile.global_rank
            user.performance_points = profile.performance_points
            user.fetched_at = observed_at

            beatmap_ids = {play.beatmap_id for play in top_plays}
            existing_beatmaps = {
                beatmap.beatmap_id: beatmap
                for beatmap in session.scalars(
                    select(Beatmap).where(Beatmap.beatmap_id.in_(beatmap_ids))
                )
            }

            for play in top_plays:
                beatmap = existing_beatmaps.get(play.beatmap_id)
                if beatmap is None:
                    beatmap = Beatmap(beatmap_id=play.beatmap_id)
                    session.add(beatmap)
                    existing_beatmaps[play.beatmap_id] = beatmap

                beatmap.beatmapset_id = play.beatmapset_id
                beatmap.artist = play.artist
                beatmap.title = play.title
                beatmap.difficulty_name = play.difficulty_name
                beatmap.star_rating = play.star_rating
                beatmap.approach_rate = play.approach_rate
                beatmap.bpm = play.bpm
                beatmap.fetched_at = observed_at

            session.execute(
                delete(UserTopPlay).where(UserTopPlay.user_id == profile.user_id)
            )

            for position, play in enumerate(top_plays, start=1):
                session.add(
                    UserTopPlay(
                        user_id=profile.user_id,
                        beatmap_id=play.beatmap_id,
                        score_id=play.score_id,
                        position=position,
                        performance_points=play.performance_points,
                        accuracy=play.accuracy,
                        grade=play.grade,
                        mods=list(play.mods),
                        max_combo=play.max_combo,
                        played_at=parse_played_at(play.played_at),
                        fetched_at=observed_at,
                    )
                )

    return PersistenceResult(
        user_id=profile.user_id,
        username=profile.username,
        top_play_count=len(top_plays),
        beatmap_count=len({play.beatmap_id for play in top_plays}),
    )

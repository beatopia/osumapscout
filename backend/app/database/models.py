"""SQLAlchemy models for the current-state persistence schema."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base shared by the application's ORM models."""


class User(Base):
    """An osu! user and the most recently fetched profile metadata."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    global_rank: Mapped[int | None] = mapped_column(BigInteger)
    performance_points: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    top_plays: Mapped[list["UserTopPlay"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Beatmap(Base):
    """One osu! beatmap difficulty and its most recently fetched metadata."""

    __tablename__ = "beatmaps"

    beatmap_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    beatmapset_id: Mapped[int | None] = mapped_column(BigInteger)
    artist: Mapped[str | None] = mapped_column(String(512))
    title: Mapped[str | None] = mapped_column(String(512))
    difficulty_name: Mapped[str | None] = mapped_column(String(255))
    star_rating: Mapped[float | None] = mapped_column(Float)
    approach_rate: Mapped[float | None] = mapped_column(Float)
    bpm: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    top_plays: Mapped[list["UserTopPlay"]] = relationship(
        back_populates="beatmap",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserTopPlay(Base):
    """A user's current known top-play entry for one beatmap."""

    __tablename__ = "user_top_plays"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_user_top_plays_position_positive"),
        CheckConstraint(
            "accuracy IS NULL OR (accuracy >= 0 AND accuracy <= 1)",
            name="ck_user_top_plays_accuracy_range",
        ),
        CheckConstraint(
            "performance_points IS NULL OR performance_points >= 0",
            name="ck_user_top_plays_performance_points_nonnegative",
        ),
        UniqueConstraint(
            "user_id",
            "position",
            name="uq_user_top_plays_user_position",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    beatmap_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("beatmaps.beatmap_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    score_id: Mapped[int | None] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    performance_points: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    grade: Mapped[str | None] = mapped_column(String(16))
    mods: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)),
        nullable=False,
        default=list,
    )
    max_combo: Mapped[int | None] = mapped_column(Integer)
    played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="top_plays")
    beatmap: Mapped[Beatmap] = relationship(back_populates="top_plays")

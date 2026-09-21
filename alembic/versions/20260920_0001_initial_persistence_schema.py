"""Create the initial current-state persistence schema.

Revision ID: 20260920_0001
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260920_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("avatar_url", sa.String(length=2048), nullable=False),
        sa.Column("global_rank", sa.BigInteger(), nullable=True),
        sa.Column("performance_points", sa.Float(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "beatmaps",
        sa.Column("beatmap_id", sa.BigInteger(), nullable=False),
        sa.Column("beatmapset_id", sa.BigInteger(), nullable=True),
        sa.Column("artist", sa.String(length=512), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("difficulty_name", sa.String(length=255), nullable=True),
        sa.Column("star_rating", sa.Float(), nullable=True),
        sa.Column("approach_rate", sa.Float(), nullable=True),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("beatmap_id"),
    )
    op.create_table(
        "user_top_plays",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("beatmap_id", sa.BigInteger(), nullable=False),
        sa.Column("score_id", sa.BigInteger(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("performance_points", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("grade", sa.String(length=16), nullable=True),
        sa.Column("mods", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("max_combo", sa.Integer(), nullable=True),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "accuracy IS NULL OR (accuracy >= 0 AND accuracy <= 1)",
            name="ck_user_top_plays_accuracy_range",
        ),
        sa.CheckConstraint(
            "performance_points IS NULL OR performance_points >= 0",
            name="ck_user_top_plays_performance_points_nonnegative",
        ),
        sa.CheckConstraint(
            "position > 0",
            name="ck_user_top_plays_position_positive",
        ),
        sa.ForeignKeyConstraint(
            ["beatmap_id"], ["beatmaps.beatmap_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "beatmap_id"),
        sa.UniqueConstraint(
            "user_id", "position", name="uq_user_top_plays_user_position"
        ),
    )
    op.create_index(
        op.f("ix_user_top_plays_beatmap_id"),
        "user_top_plays",
        ["beatmap_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_top_plays_beatmap_id"),
        table_name="user_top_plays",
    )
    op.drop_table("user_top_plays")
    op.drop_table("beatmaps")
    op.drop_table("users")

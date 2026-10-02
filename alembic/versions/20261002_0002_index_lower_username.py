"""Index case-insensitive user lookups.

Revision ID: 20261002_0002
Revises: 20260920_0001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261002_0002"
down_revision: str | None = "20260920_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_username_lower", table_name="users")

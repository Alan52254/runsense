"""add completed activity history index

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_completed_activities_actor_history "
        "ON completed_activities (athlete_id, performed_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_completed_activities_actor_history",
        table_name="completed_activities",
    )

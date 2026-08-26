"""require finite completed activity duration

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_completed_activities_duration_finite",
        "completed_activities",
        "duration_minutes NOT IN ('Infinity'::numeric, 'NaN'::numeric)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_completed_activities_duration_finite",
        "completed_activities",
        type_="check",
    )

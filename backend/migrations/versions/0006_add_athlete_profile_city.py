"""add athlete_profiles.city and grant profile updates

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("athlete_profiles", sa.Column("city", sa.Text(), nullable=True))
    # athlete_profiles was SELECT-only until now (0002) — PATCH /profile is
    # the first route that writes to it.
    op.execute("GRANT UPDATE ON athlete_profiles TO runsense_runtime")


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON athlete_profiles FROM runsense_runtime")
    op.drop_column("athlete_profiles", "city")

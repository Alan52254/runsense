"""create weather_cache

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # City-keyed, not athlete-keyed: weather isn't athlete-owned data
    # (REQ-DATAOWN-001 governs athlete-owned records; a city's weather isn't
    # one), so no RLS here — see design.md Decision 1.
    op.create_table(
        "weather_cache",
        sa.Column("city", sa.Text(), primary_key=True),
        sa.Column("temperature_c", sa.Numeric(), nullable=False),
        sa.Column("humidity_pct", sa.Numeric(), nullable=False),
        sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "humidity_pct >= 0 AND humidity_pct <= 100", name="ck_weather_cache_humidity"
        ),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON weather_cache TO runsense_runtime")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, UPDATE ON weather_cache FROM runsense_runtime")
    op.drop_table("weather_cache")

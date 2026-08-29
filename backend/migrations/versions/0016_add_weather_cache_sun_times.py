"""add weather_cache sunrise/sunset/utc_offset

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-25

Needed for app/diurnal_temperature.py's time-of-day estimate, which reads
sunrise/sunset even when a request is served from the cache (the common
case, given the 10-minute cache window) rather than a fresh live fetch.
Nullable because rows written before this migration won't have them --
weather.py falls back to skipping the diurnal estimate for those, exactly
like it already does for a city with no climate-normal entry.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("weather_cache", sa.Column("sunrise_utc", sa.DateTime(timezone=True), nullable=True))
    op.add_column("weather_cache", sa.Column("sunset_utc", sa.DateTime(timezone=True), nullable=True))
    op.add_column("weather_cache", sa.Column("utc_offset_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("weather_cache", "utc_offset_seconds")
    op.drop_column("weather_cache", "sunset_utc")
    op.drop_column("weather_cache", "sunrise_utc")

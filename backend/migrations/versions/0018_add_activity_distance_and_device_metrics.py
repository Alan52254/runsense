"""add distance_km and device_metrics to completed_activities

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-25

distance_km: a real, universal column (unlike device_metrics below) -- the
manual-log form already collects distance from the athlete and was
silently discarding it before this change (CreateActivityRequest had no
field for it). Nullable: most historical manual entries never had a
distance typed in.

device_metrics: JSON passthrough, same untyped-blob pattern as
0013/0017's `structure` column -- holds whatever device-reported training
metrics a provider supplies (heart rate, cadence, elevation, calories,
training effect) that don't have a universal column of their own, since
manual entries will never have them. Read-only from the API's perspective
today: nothing currently POSTs this field, it's populated by
backfill_garmin_metrics.py directly.
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("completed_activities", sa.Column("distance_km", sa.Numeric(), nullable=True))
    op.add_column(
        "completed_activities",
        sa.Column("device_metrics", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("completed_activities", "device_metrics")
    op.drop_column("completed_activities", "distance_km")

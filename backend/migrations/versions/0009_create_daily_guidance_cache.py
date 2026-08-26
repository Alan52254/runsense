"""create daily_guidance_cache

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Athlete-owned derived data (it's computed from the athlete's own
    # training load) — RLS actor-scoped like completed_activities /
    # training_load_daily, not city-scoped like weather_cache.
    op.create_table(
        "daily_guidance_cache",
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("recommendation_json", JSONB(), nullable=False),
        sa.Column(
            "tone_variant_id",
            sa.Text(),
            sa.ForeignKey("tone_variant_templates.tone_variant_id"),
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("athlete_id", "local_date", name="pk_daily_guidance_cache"),
    )
    op.execute("GRANT SELECT, INSERT ON daily_guidance_cache TO runsense_runtime")
    op.execute("ALTER TABLE daily_guidance_cache ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE daily_guidance_cache FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY daily_guidance_cache_actor_rw ON daily_guidance_cache
          TO runsense_runtime
          USING (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
          WITH CHECK (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS daily_guidance_cache_actor_rw ON daily_guidance_cache")
    op.execute("REVOKE SELECT, INSERT ON daily_guidance_cache FROM runsense_runtime")
    op.drop_table("daily_guidance_cache")

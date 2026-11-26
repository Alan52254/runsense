"""create athlete_wellness_daily table with forced RLS for Garmin wellness streams

Stores daily resting heart rate, HRV, sleep, Body Battery, stress, VO2max, and
race-prediction metrics keyed by (athlete_id, local_date). Forced RLS limits
writes to the athlete themselves and coach reads to athletes who granted the
`training_load` consent scope (`app_actor_can_read_athlete`).

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "athlete_wellness_daily",
        sa.Column(
            "athlete_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("resting_hr_bpm", sa.Integer(), nullable=True),
        sa.Column("hrv_ms", sa.Float(), nullable=True),
        sa.Column("hrv_status", sa.Text(), nullable=True),
        sa.Column("sleep_hours", sa.Float(), nullable=True),
        sa.Column("sleep_score", sa.Integer(), nullable=True),
        sa.Column("body_battery_high", sa.Integer(), nullable=True),
        sa.Column("body_battery_low", sa.Integer(), nullable=True),
        sa.Column("body_battery_recent", sa.Integer(), nullable=True),
        sa.Column("stress_avg", sa.Integer(), nullable=True),
        sa.Column("vo2max", sa.Float(), nullable=True),
        sa.Column("race_pred_5k_s", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="garmin_gdpr"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("athlete_id", "local_date", name="pk_athlete_wellness_daily"),
    )
    op.create_index(
        "ix_athlete_wellness_daily_athlete_date",
        "athlete_wellness_daily",
        ["athlete_id", sa.text("local_date DESC")],
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON athlete_wellness_daily TO runsense_runtime")
    op.execute("ALTER TABLE athlete_wellness_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE athlete_wellness_daily FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY athlete_wellness_daily_actor_rw ON athlete_wellness_daily
          TO runsense_runtime
          USING (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
          WITH CHECK (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
        """
    )
    op.execute(
        """
        CREATE POLICY athlete_wellness_daily_coach_read ON athlete_wellness_daily
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_athlete(athlete_id, 'training_load'))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS athlete_wellness_daily_coach_read ON athlete_wellness_daily")
    op.execute("DROP POLICY IF EXISTS athlete_wellness_daily_actor_rw ON athlete_wellness_daily")
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON athlete_wellness_daily FROM runsense_runtime")
    op.drop_index("ix_athlete_wellness_daily_athlete_date", table_name="athlete_wellness_daily")
    op.drop_table("athlete_wellness_daily")

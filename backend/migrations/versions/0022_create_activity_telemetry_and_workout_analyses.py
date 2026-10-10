"""per-second telemetry, confirmed workout analyses, athlete HR settings

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-09

activity_telemetry: one row per Completed Activity that came with a device
file -- the 1 Hz distance / speed / heart-rate / cadence samples, the
watch's own laps (incl. how each was triggered), timer pause / resume
events and the HR settings the watch used that day. Before this, History
had no per-lap data at all (see web/src/lib/lapSynthesis.ts) and per-lap
heart rate was synthesized; with this table History shows what the watch
actually recorded. auto_detection caches the workout-structure detection
(app/workout_segmentation.py) so History can label laps and find "the last
time you ran this same session" without re-running it per request.

workout_analyses: the athlete-confirmed segmentation of one activity and
the analysis computed from it (metrics, findings, coach write-up). One per
activity; re-analysing replaces it.

athlete_profiles.max_hr_bpm / resting_hr_bpm / birth_year: the athlete's
own HR settings, first in the max-HR priority order (manual > watch >
recorded history > age formula, see app/workout_analysis.py).

Both new tables follow completed_activities' RLS shape: the runtime role
sees and writes only rows whose athlete_id is the transaction's actor.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_ACTOR = "NULLIF(current_setting('app.actor_user_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "activity_telemetry",
        sa.Column("activity_id", UUID(as_uuid=True), sa.ForeignKey("completed_activities.id"), primary_key=True),
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="garmin_fit"),
        sa.Column("sport", sa.Text(), nullable=True),
        sa.Column("sub_sport", sa.Text(), nullable=True),
        sa.Column("device", sa.Text(), nullable=True),
        sa.Column("hr_profile", JSONB(), nullable=False, server_default="{}"),
        sa.Column("laps", JSONB(), nullable=False, server_default="[]"),
        sa.Column("timer_events", JSONB(), nullable=False, server_default="[]"),
        sa.Column("workout_steps", JSONB(), nullable=False, server_default="[]"),
        sa.Column("samples", JSONB(), nullable=False),
        sa.Column("hr_peak_30s", sa.Integer(), nullable=True),
        sa.Column("auto_detection", JSONB(), nullable=True),
        sa.Column("auto_summary", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_activity_telemetry_athlete", "activity_telemetry", ["athlete_id"])

    op.create_table(
        "workout_analyses",
        sa.Column("activity_id", UUID(as_uuid=True), sa.ForeignKey("completed_activities.id"), primary_key=True),
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_type", sa.Text(), nullable=False),
        sa.Column("segments", JSONB(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("target_pace_s_per_km", sa.Numeric(), nullable=True),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("narrative_source", sa.Text(), nullable=False),
        sa.Column("narrative_model", sa.Text(), nullable=True),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "session_type IN ('intervals', 'tempo', 'easy', 'long', 'race', 'other')",
            name="ck_workout_analyses_session_type",
        ),
        sa.CheckConstraint("narrative_source IN ('llm', 'offline')", name="ck_workout_analyses_narrative_source"),
    )
    op.create_index("ix_workout_analyses_athlete", "workout_analyses", ["athlete_id"])

    op.add_column("athlete_profiles", sa.Column("max_hr_bpm", sa.Integer(), nullable=True))
    op.add_column("athlete_profiles", sa.Column("resting_hr_bpm", sa.Integer(), nullable=True))
    op.add_column("athlete_profiles", sa.Column("birth_year", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_athlete_profiles_max_hr", "athlete_profiles", "max_hr_bpm IS NULL OR max_hr_bpm BETWEEN 120 AND 230"
    )
    op.create_check_constraint(
        "ck_athlete_profiles_resting_hr", "athlete_profiles",
        "resting_hr_bpm IS NULL OR resting_hr_bpm BETWEEN 30 AND 100",
    )
    op.create_check_constraint(
        "ck_athlete_profiles_birth_year", "athlete_profiles", "birth_year IS NULL OR birth_year BETWEEN 1920 AND 2020"
    )

    for table in ("activity_telemetry", "workout_analyses"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO runsense_runtime")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_actor_rw ON {table}
              TO runsense_runtime
              USING (athlete_id = {_ACTOR})
              WITH CHECK (athlete_id = {_ACTOR})
            """
        )


def downgrade() -> None:
    for table in ("workout_analyses", "activity_telemetry"):
        op.execute(f"DROP POLICY IF EXISTS {table}_actor_rw ON {table}")
        op.execute(f"REVOKE SELECT, INSERT, UPDATE ON {table} FROM runsense_runtime")
    op.drop_constraint("ck_athlete_profiles_birth_year", "athlete_profiles", type_="check")
    op.drop_constraint("ck_athlete_profiles_resting_hr", "athlete_profiles", type_="check")
    op.drop_constraint("ck_athlete_profiles_max_hr", "athlete_profiles", type_="check")
    op.drop_column("athlete_profiles", "birth_year")
    op.drop_column("athlete_profiles", "resting_hr_bpm")
    op.drop_column("athlete_profiles", "max_hr_bpm")
    op.drop_index("ix_workout_analyses_athlete", table_name="workout_analyses")
    op.drop_table("workout_analyses")
    op.drop_index("ix_activity_telemetry_athlete", table_name="activity_telemetry")
    op.drop_table("activity_telemetry")

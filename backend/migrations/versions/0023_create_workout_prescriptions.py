"""workout prescriptions ("課表要求") and the device activity name

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-09

workout_prescriptions: what was prescribed for one activity, rep by rep
(blocks of reps with per-rep target paces and recoveries), and where that
came from: athlete_text (typed by the athlete) or activity_name (parsed from
the workout the athlete wrote into the Garmin activity name). A coach's
assignment is read live from assigned_workouts and an inferred prescription
is recomputed from the run, so neither is stored here. See
app/workout_prescription.py.

activity_telemetry.activity_name: the activity's name on the device /
Garmin Connect -- often the athlete's own note of the workout
("400 x 10 組休1分鐘 84/圈").
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_ACTOR = "NULLIF(current_setting('app.actor_user_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("activity_telemetry", sa.Column("activity_name", sa.Text(), nullable=True))
    op.create_table(
        "workout_prescriptions",
        sa.Column("activity_id", UUID(as_uuid=True), sa.ForeignKey("completed_activities.id"), primary_key=True),
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("prescription", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('athlete_text', 'activity_name')", name="ck_workout_prescriptions_source"),
    )
    op.create_index("ix_workout_prescriptions_athlete", "workout_prescriptions", ["athlete_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON workout_prescriptions TO runsense_runtime")
    op.execute("ALTER TABLE workout_prescriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workout_prescriptions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY workout_prescriptions_actor_rw ON workout_prescriptions
          TO runsense_runtime
          USING (athlete_id = {_ACTOR})
          WITH CHECK (athlete_id = {_ACTOR})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS workout_prescriptions_actor_rw ON workout_prescriptions")
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON workout_prescriptions FROM runsense_runtime")
    op.drop_index("ix_workout_prescriptions_athlete", table_name="workout_prescriptions")
    op.drop_table("workout_prescriptions")
    op.drop_column("activity_telemetry", "activity_name")

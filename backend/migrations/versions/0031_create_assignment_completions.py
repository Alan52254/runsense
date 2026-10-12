"""record which run completed which assigned workout

An athlete uploading a run completes an Assigned Workout -- that day's, or,
when the workout was moved, one within three days that has the same reps
and distances (app/activity_upload.py). The link lives here rather than on
assigned_workouts: the assignment stays the coach's (only a coach writes
it), while the athlete records, and may correct, which of their own runs
completed it. A coach of the team reads the link; the run's date is kept on
the row so "已完成（改在 10/9）" shows even without the activity_summary
Consent Scope that reading the run itself needs.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

_ACTOR = "NULLIF(current_setting('app.actor_user_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "assignment_completions",
        sa.Column("assigned_workout_id", UUID(as_uuid=True),
                  sa.ForeignKey("assigned_workouts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("activity_id", UUID(as_uuid=True),
                  sa.ForeignKey("completed_activities.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("activity_local_date", sa.Date(), nullable=False),
        sa.Column("linked_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("linked_by IN ('auto', 'athlete')", name="ck_assignment_completions_linked_by"),
    )
    op.create_index("ix_assignment_completions_athlete", "assignment_completions", ["athlete_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON assignment_completions TO runsense_runtime")
    op.execute("ALTER TABLE assignment_completions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assignment_completions FORCE ROW LEVEL SECURITY")
    # the athlete links only their own run to their own assignment
    op.execute(
        f"""
        CREATE POLICY assignment_completions_athlete_rw ON assignment_completions
          TO runsense_runtime
          USING (athlete_id = {_ACTOR})
          WITH CHECK (
            athlete_id = {_ACTOR}
            AND EXISTS (SELECT 1 FROM assigned_workouts w
                         WHERE w.id = assigned_workout_id AND w.athlete_id = {_ACTOR})
            AND EXISTS (SELECT 1 FROM completed_activities a
                         WHERE a.id = activity_id AND a.athlete_id = {_ACTOR})
          )
        """
    )
    op.execute(
        """
        CREATE POLICY assignment_completions_coach_read ON assignment_completions
          FOR SELECT TO runsense_runtime
          USING (EXISTS (SELECT 1 FROM assigned_workouts w
                          WHERE w.id = assigned_workout_id AND app_actor_is_active_team_coach(w.team_id)))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS assignment_completions_coach_read ON assignment_completions")
    op.execute("DROP POLICY IF EXISTS assignment_completions_athlete_rw ON assignment_completions")
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON assignment_completions FROM runsense_runtime")
    op.drop_table("assignment_completions")

"""let a coach read an athlete's saved workout analyses

The weekly Schedule Draft a coach reviews carries the "下次" advice from the
athlete's latest Workout Analysis. A coach could already read the athlete's
Completed Activities under the `activity_summary` Consent Scope; a Workout
Analysis is a reading of one of those activities, so it is shared under the
same scope and no wider. Writing stays the athlete's own.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY workout_analyses_coach_read ON workout_analyses
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_athlete(athlete_id, 'activity_summary'))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS workout_analyses_coach_read ON workout_analyses")

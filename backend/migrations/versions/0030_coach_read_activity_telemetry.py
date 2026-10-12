"""let a coach read an athlete's recorded telemetry

A coach opening an assigned workout sees what the athlete actually ran: the
athlete's own Workout Analysis when there is one, otherwise a read-only
reading of the recording from the import-time detection (computed on
request, never stored). That reading needs the per-second recording. It is
shared under the same `activity_summary` Consent Scope as the Completed
Activity and the Workout Analysis (0028) and no wider; writing stays the
athlete's own.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY activity_telemetry_coach_read ON activity_telemetry
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_athlete(athlete_id, 'activity_summary'))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS activity_telemetry_coach_read ON activity_telemetry")

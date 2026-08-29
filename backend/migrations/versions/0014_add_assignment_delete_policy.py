"""grant delete + coach-delete RLS policy on assigned_workouts

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-25

AssignmentsScreen.tsx gained a "delete this assignment" affordance for
coaches; migration 0012 only granted SELECT/INSERT on assigned_workouts, so
DELETE FROM assigned_workouts would fail both on the GRANT and (once
granted) on row-level security with no matching policy. This mirrors
0012's assigned_workouts_coach_insert policy shape, using the same
app_actor_is_active_team_coach(team_id) helper from migration 0010.
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT DELETE ON assigned_workouts TO runsense_runtime")
    op.execute(
        """
        CREATE POLICY assigned_workouts_coach_delete ON assigned_workouts
          FOR DELETE TO runsense_runtime
          USING (app_actor_is_active_team_coach(team_id))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS assigned_workouts_coach_delete ON assigned_workouts")
    op.execute("REVOKE DELETE ON assigned_workouts FROM runsense_runtime")

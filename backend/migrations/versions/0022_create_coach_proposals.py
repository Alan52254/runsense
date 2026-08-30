"""create athlete-owned coach proposal records

A Coach Proposal is a Ranked Plan worked out from facts the Athlete stated in
conversation. It is stored so the Athlete can see how their plan has been
adapting, and so an accepted one can shape that day's evaluation.

Storing only the Scenario Override -- never a workout -- is deliberate: the
plan is always re-derived by the reviewed engine from the stored facts, so an
accepted proposal cannot outlive or contradict a change to the rules (ADR
0002).

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coach_proposals",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("athlete_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("local_training_date", sa.Date(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        # The stated facts, exactly as validated. No workout is stored.
        sa.Column("scenario_override", JSONB(), nullable=False),
        sa.Column("changed_facts", sa.ARRAY(sa.Text()), nullable=False),
        # A summary of what the reviewed engine produced at proposal time,
        # kept for the Athlete's own record rather than for re-use.
        sa.Column("plan_summary", JSONB(), nullable=False),
        sa.Column("ranker_version", sa.Text(), nullable=False),
        sa.Column("abstained", sa.Boolean(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "accepted_at IS NULL OR dismissed_at IS NULL",
            name="ck_coach_proposals_single_outcome",
        ),
    )
    op.create_index(
        "ix_coach_proposals_athlete_date",
        "coach_proposals",
        ["athlete_id", "local_training_date", "proposed_at"],
    )
    # At most one accepted proposal shapes any one day.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_coach_proposals_accepted_day
            ON coach_proposals (athlete_id, local_training_date)
         WHERE accepted_at IS NOT NULL
        """
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON coach_proposals TO runsense_runtime"
    )
    op.execute("ALTER TABLE coach_proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE coach_proposals FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY coach_proposals_self_read ON coach_proposals
          FOR SELECT TO runsense_runtime
          USING (athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY coach_proposals_self_insert ON coach_proposals
          FOR INSERT TO runsense_runtime
          WITH CHECK (athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY coach_proposals_self_update ON coach_proposals
          FOR UPDATE TO runsense_runtime
          USING (athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
          WITH CHECK (athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    # A Coach sees that a day was adapted only where the Athlete already
    # shares their training load. No new Consent Scope is introduced.
    op.execute(
        """
        CREATE POLICY coach_proposals_coach_read ON coach_proposals
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_athlete(athlete_id, 'training_load'))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS coach_proposals_coach_read ON coach_proposals")
    op.execute("DROP POLICY IF EXISTS coach_proposals_self_update ON coach_proposals")
    op.execute("DROP POLICY IF EXISTS coach_proposals_self_insert ON coach_proposals")
    op.execute("DROP POLICY IF EXISTS coach_proposals_self_read ON coach_proposals")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON coach_proposals FROM runsense_runtime")
    op.execute("DROP INDEX IF EXISTS ux_coach_proposals_accepted_day")
    op.drop_index("ix_coach_proposals_athlete_date", table_name="coach_proposals")
    op.drop_table("coach_proposals")

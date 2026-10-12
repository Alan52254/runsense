"""record what the coach decided, day by day, against what the system suggested

One row per athlete and Local Training Date a coach decided on: the system's
suggestion (when there was one), what the coach published or recorded, the
outcome, which fields changed and why. Written only by app/assignment_service
-- for a reviewed Schedule Draft, a retrospective review that publishes
nothing, a manual assignment, and a plan the coach wrote in chat. It is the
audit trail of the Coach Review and the evidence base for the coach review
study.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignment_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("athlete_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("suggested", JSONB(), nullable=True),
        sa.Column("final", JSONB(), nullable=True),
        sa.Column("changed_fields", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("card_id", UUID(as_uuid=True), sa.ForeignKey("chat_cards.id"), nullable=True),
        sa.Column("draft_version", sa.Integer(), nullable=True),
        sa.Column("batch_id", UUID(as_uuid=True), sa.ForeignKey("assignment_batches.id"), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("decided_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('review_card', 'retrospective_review', 'manual_assignment', 'chat_plan')",
                           name="ck_assignment_decisions_source"),
        sa.CheckConstraint("outcome IN ('accepted', 'edited', 'removed', 'coach_authored', 'insufficient_data')",
                           name="ck_assignment_decisions_outcome"),
        sa.CheckConstraint("char_length(reason) <= 500", name="ck_assignment_decisions_reason"),
    )
    op.create_index("ix_assignment_decisions_team_athlete", "assignment_decisions",
                    ["team_id", "athlete_id", "local_date"])

    op.execute("GRANT SELECT, INSERT ON assignment_decisions TO runsense_runtime")
    op.execute("ALTER TABLE assignment_decisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assignment_decisions FORCE ROW LEVEL SECURITY")
    # the review is the coach's own record; the athlete sees the result as
    # Assigned Workouts, not the deliberation
    op.execute(
        """
        CREATE POLICY assignment_decisions_coach_rw ON assignment_decisions TO runsense_runtime
          USING (app_actor_is_active_team_coach(team_id))
          WITH CHECK (app_actor_is_active_team_coach(team_id))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS assignment_decisions_coach_rw ON assignment_decisions")
    op.execute("REVOKE SELECT, INSERT ON assignment_decisions FROM runsense_runtime")
    op.drop_index("ix_assignment_decisions_team_athlete", table_name="assignment_decisions")
    op.drop_table("assignment_decisions")

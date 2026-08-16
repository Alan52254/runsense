"""create completed_activities table with RLS

Revision ID: 0001
Revises:
Create Date: 2026-08-08

Implements tasks.md sections 1 (PostgreSQL Schema) and 2 (Row-Level
Security) for manual-workout-create-sync. See design.md Decisions 1, 2, 4
for the rationale behind the column choices and the RLS policy shape.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "completed_activities",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        # athlete-owned: no team_id column (REQ-DATAOWN-001, TC-SCHEMA-DATAOWN-001)
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("client_mutation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        # provider_activity_id is nullable TEXT, not UUID: it's an external
        # identifier owned by whatever provider's ID space, always NULL for
        # manual entries in this change. See design.md Decision 4.
        sa.Column("provider", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("provider_activity_id", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Numeric(), nullable=False),
        sa.Column("rpe", sa.SmallInteger(), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        # server-derived and persisted (design.md Decision 5), not
        # client-supplied
        sa.Column("timezone_snapshot", sa.Text(), nullable=False),
        sa.Column("local_training_date", sa.Date(), nullable=False),
        sa.Column("session_load", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False, server_default="AU"),
        sa.Column("source_metric", sa.Text(), nullable=False, server_default="SESSION_RPE"),
        # migration-prep column only; not incremented by this change
        # (design.md Risks/Trade-offs). Editing is deferred to
        # manual-workout-edit-sync.
        sa.Column("server_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )

    op.create_check_constraint(
        "ck_completed_activities_rpe_range", "completed_activities", "rpe BETWEEN 1 AND 10"
    )
    op.create_check_constraint(
        "ck_completed_activities_duration_positive",
        "completed_activities",
        "duration_minutes > 0",
    )

    # idempotency key (design.md Decision 3)
    op.create_unique_constraint(
        "uq_completed_activities_athlete_mutation",
        "completed_activities",
        ["athlete_id", "client_mutation_id"],
    )

    # REQ-DEDUP-001: partial index so a future provider integration is
    # structurally correct without manual entries (provider_activity_id
    # always NULL) ever exercising it. See design.md Decision 4.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_completed_activities_provider_activity
        ON completed_activities (provider, provider_activity_id)
        WHERE provider_activity_id IS NOT NULL
        """
    )

    # --- Runtime role: dev/test convenience, not production provisioning ---
    # Production credentials, rotation, and grants are an ops concern.
    # This block is idempotent so local/dev/test environments can run this
    # migration standalone. It deliberately does not grant BYPASSRLS or
    # superuser (REQ-RLS-002) and does not make the role the table owner
    # (REQ-RLS-001) -- ownership stays with whichever role ran this
    # migration.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'runsense_runtime') THEN
            CREATE ROLE runsense_runtime LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
          END IF;
        END
        $$;
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON completed_activities TO runsense_runtime")

    # REQ-RLS-003 (TC-RLS-010): both must be true.
    op.execute("ALTER TABLE completed_activities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE completed_activities FORCE ROW LEVEL SECURITY")

    # design.md Decision 2: USING + WITH CHECK, NULL-safe actor lookup so a
    # missing/malformed app.actor_user_id fails closed rather than raising.
    op.execute(
        """
        CREATE POLICY completed_activities_actor_rw ON completed_activities
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
    op.execute("DROP POLICY IF EXISTS completed_activities_actor_rw ON completed_activities")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON completed_activities FROM runsense_runtime")
    op.drop_table("completed_activities")

"""create auth_sessions, audit_log, assigned_workouts; add users.deletion_requested_at

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-24

Implements the two items pulled back into scope from docs/mvp-checklist.md's
"Deferred past MVP" section: Settings (Security/Privacy/Integration) and
Coach Assignments. See backend/app/routes/settings.py and
backend/app/routes/assignments.py.

Deliberately demo-appropriate, not full compliance infrastructure:
- auth_sessions is populated at demo login (app/routes/demo_auth.py) and
  carries a `mfa_satisfied` flag scoped to that one session/login, not a
  real MFA/TOTP integration (REQ-AUTH-007 gate demonstration only).
- audit_log's `event` is constrained to the exact 8-value enum already in
  web/src/lib/types.ts `AuditEvent`; `summary` is always a short
  server-constructed string, never free text/payload (REQ-AUDIT-002).
- assigned_workouts reuses the existing `app_actor_is_active_team_coach`
  helper from migration 0010 rather than inventing a parallel one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_AUDIT_EVENTS = (
    "AUTH_LOGIN",
    "AUTH_FAILURE",
    "ROLE_CHANGE",
    "CONSENT_GRANT",
    "CONSENT_REVOKE",
    "DATA_EXPORT",
    "CROSS_TENANT_DENIED",
    "BILLING_CHANGE",
)


def upgrade() -> None:
    op.add_column("users", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("GRANT UPDATE (deletion_requested_at) ON users TO runsense_runtime")

    op.create_table(
        "auth_sessions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device", sa.Text(), nullable=False),
        sa.Column("ip_masked", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_satisfied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["user_id", "revoked_at"])

    op.create_table(
        "audit_log",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "event IN (" + ", ".join(f"'{e}'" for e in _AUDIT_EVENTS) + ")",
            name="ck_audit_log_event",
        ),
    )
    op.create_index("ix_audit_log_actor_created", "audit_log", ["actor_id", "created_at"])

    op.create_table(
        "assigned_workouts",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("athlete_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("intensity_label", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'SCHEDULED'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'COMPLETED', 'MISSED')",
            name="ck_assigned_workouts_status",
        ),
    )
    op.create_index(
        "ix_assigned_workouts_team_date", "assigned_workouts", ["team_id", "local_date"]
    )
    op.create_index(
        "ix_assigned_workouts_athlete_date", "assigned_workouts", ["athlete_id", "local_date"]
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON auth_sessions TO runsense_runtime")
    op.execute("GRANT SELECT, INSERT ON audit_log TO runsense_runtime")
    op.execute("GRANT SELECT, INSERT ON assigned_workouts TO runsense_runtime")

    for table in ("auth_sessions", "audit_log", "assigned_workouts"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY auth_sessions_self_read ON auth_sessions
          FOR SELECT TO runsense_runtime
          USING (user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY auth_sessions_self_insert ON auth_sessions
          FOR INSERT TO runsense_runtime
          WITH CHECK (user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY auth_sessions_self_update ON auth_sessions
          FOR UPDATE TO runsense_runtime
          USING (user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
          WITH CHECK (user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        CREATE POLICY audit_log_self_read ON audit_log
          FOR SELECT TO runsense_runtime
          USING (actor_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY audit_log_self_insert ON audit_log
          FOR INSERT TO runsense_runtime
          WITH CHECK (actor_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        CREATE POLICY assigned_workouts_self_or_coach_read ON assigned_workouts
          FOR SELECT TO runsense_runtime
          USING (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            OR app_actor_is_active_team_coach(team_id)
          )
        """
    )
    op.execute(
        """
        CREATE POLICY assigned_workouts_coach_insert ON assigned_workouts
          FOR INSERT TO runsense_runtime
          WITH CHECK (
            app_actor_is_active_team_coach(team_id)
            AND EXISTS (
              SELECT 1 FROM team_memberships tm
               WHERE tm.team_id = assigned_workouts.team_id
                 AND tm.user_id = assigned_workouts.athlete_id
                 AND tm.role = 'athlete'
                 AND tm.status = 'ACTIVE'
            )
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS assigned_workouts_coach_insert ON assigned_workouts")
    op.execute("DROP POLICY IF EXISTS assigned_workouts_self_or_coach_read ON assigned_workouts")
    op.execute("DROP POLICY IF EXISTS audit_log_self_insert ON audit_log")
    op.execute("DROP POLICY IF EXISTS audit_log_self_read ON audit_log")
    op.execute("DROP POLICY IF EXISTS auth_sessions_self_update ON auth_sessions")
    op.execute("DROP POLICY IF EXISTS auth_sessions_self_insert ON auth_sessions")
    op.execute("DROP POLICY IF EXISTS auth_sessions_self_read ON auth_sessions")
    op.execute("REVOKE SELECT, INSERT ON assigned_workouts FROM runsense_runtime")
    op.execute("REVOKE SELECT, INSERT ON audit_log FROM runsense_runtime")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON auth_sessions FROM runsense_runtime")
    op.drop_table("assigned_workouts")
    op.drop_table("audit_log")
    op.drop_table("auth_sessions")
    op.execute("REVOKE UPDATE (deletion_requested_at) ON users FROM runsense_runtime")
    op.drop_column("users", "deletion_requested_at")

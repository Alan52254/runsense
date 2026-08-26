"""create teams, team_memberships, consent_grants

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-24

Implements docs/mvp-checklist.md Backlog Item 1 ("Coach Team Overview +
Coach Athlete Detail"). See CONTEXT.md for Team / Team Role / Team
Membership / Coach Roster Row / Consent Scope definitions.

RLS keeps app.actor_user_id equal to the verified Actor for every query.
SECURITY DEFINER predicates inspect current Team Membership and Consent
Scope without recursive policy evaluation. Athlete-owned tables gain
SELECT-only coach policies; their self-write policies remain unchanged.

consent_grants here is intentionally minimal: enough to gate which Coach
Roster Row fields a projection includes. Full consent-grant CRUD
(`GET/PATCH /me/consent-grants`) is Backlog Item 2's job, not this one's --
this table's shape may need to be revisited then.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_COACH_ROLES = "('coach', 'head_coach', 'owner')"


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )

    op.create_table(
        "team_memberships",
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "invited_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("team_id", "user_id", name="pk_team_memberships"),
        sa.CheckConstraint(
            "role IN ('athlete', 'coach', 'head_coach', 'owner')",
            name="ck_team_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INVITED', 'LEFT')",
            name="ck_team_memberships_status",
        ),
    )
    op.create_index(
        "ix_team_memberships_team_role_status",
        "team_memberships",
        ["team_id", "role", "status"],
    )

    op.create_table(
        "consent_grants",
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("athlete_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("team_id", "athlete_id", "scope", name="pk_consent_grants"),
        sa.CheckConstraint(
            "scope IN ('activity_summary', 'training_load', 'injury_status', 'injury_detail')",
            name="ck_consent_grants_scope",
        ),
    )

    # --- users.display_name: the Coach Roster Row needs a human-readable
    # name and `users` currently only has `email`/`password_hash`. Nullable
    # so existing rows (and the demo login path, which never writes it)
    # keep working; the roster projection falls back to the email's local
    # part when unset. ---
    op.add_column("users", sa.Column("display_name", sa.Text(), nullable=True))

    op.execute("GRANT SELECT ON teams, team_memberships, consent_grants TO runsense_runtime")
    op.execute("GRANT UPDATE ON team_memberships TO runsense_runtime")
    op.execute("GRANT INSERT, UPDATE, DELETE ON consent_grants TO runsense_runtime")

    for table in ("teams", "team_memberships", "consent_grants"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE FUNCTION app_actor_has_team_membership(target_team_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT EXISTS (
            SELECT 1 FROM team_memberships tm
             WHERE tm.team_id = target_team_id
               AND tm.user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app_actor_is_active_team_coach(target_team_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT EXISTS (
            SELECT 1 FROM team_memberships tm
             WHERE tm.team_id = target_team_id
               AND tm.user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
               AND tm.role IN {_COACH_ROLES}
               AND tm.status = 'ACTIVE'
          )
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app_actor_can_read_athlete(target_athlete_id uuid, required_scope text)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT EXISTS (
            SELECT 1
              FROM team_memberships coach
              JOIN team_memberships athlete
                ON athlete.team_id = coach.team_id
               AND athlete.user_id = target_athlete_id
               AND athlete.role = 'athlete'
               AND athlete.status = 'ACTIVE'
              JOIN consent_grants grant_row
                ON grant_row.team_id = coach.team_id
               AND grant_row.athlete_id = athlete.user_id
               AND grant_row.scope = required_scope
               AND grant_row.granted = true
             WHERE coach.user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
               AND coach.role IN {_COACH_ROLES}
               AND coach.status = 'ACTIVE'
          )
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app_team_primary_coach_name(target_team_id uuid)
        RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT COALESCE(u.display_name, split_part(u.email, '@', 1))
            FROM team_memberships tm
            JOIN users u ON u.id = tm.user_id
           WHERE tm.team_id = target_team_id
             AND tm.role IN {_COACH_ROLES}
             AND tm.status = 'ACTIVE'
             AND app_actor_has_team_membership(target_team_id)
           ORDER BY CASE tm.role WHEN 'owner' THEN 1 WHEN 'head_coach' THEN 2 ELSE 3 END,
                    COALESCE(u.display_name, u.email)
           LIMIT 1
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app_actor_has_team_membership(uuid) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app_actor_is_active_team_coach(uuid) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app_actor_can_read_athlete(uuid, text) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app_team_primary_coach_name(uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_actor_has_team_membership(uuid), "
        "app_actor_is_active_team_coach(uuid), "
        "app_actor_can_read_athlete(uuid, text), "
        "app_team_primary_coach_name(uuid) "
        "TO runsense_runtime"
    )

    op.execute(
        """
        CREATE POLICY teams_member_read ON teams
          TO runsense_runtime
          USING (app_actor_has_team_membership(id))
        """
    )

    op.execute(
        """
        CREATE POLICY team_memberships_self_or_coach_read ON team_memberships
          FOR SELECT
          TO runsense_runtime
          USING (
            user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            OR app_actor_is_active_team_coach(team_id)
          )
        """
    )
    op.execute(
        """
        CREATE POLICY team_memberships_athlete_update ON team_memberships
          FOR UPDATE TO runsense_runtime
          USING (
            user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            AND role = 'athlete'
          )
          WITH CHECK (
            user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            AND role = 'athlete'
          )
        """
    )

    op.execute(
        """
        CREATE POLICY consent_grants_self_or_coach_read ON consent_grants
          FOR SELECT
          TO runsense_runtime
          USING (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            OR app_actor_is_active_team_coach(team_id)
          )
        """
    )
    op.execute(
        """
        CREATE POLICY consent_grants_athlete_write ON consent_grants
          FOR ALL TO runsense_runtime
          USING (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
          WITH CHECK (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            AND EXISTS (
              SELECT 1 FROM team_memberships own_membership
               WHERE own_membership.team_id = consent_grants.team_id
                 AND own_membership.user_id = consent_grants.athlete_id
                 AND own_membership.role = 'athlete'
                 AND own_membership.status = 'ACTIVE'
            )
          )
        """
    )

    op.execute(
        """
        CREATE POLICY completed_activities_coach_read ON completed_activities
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_athlete(athlete_id, 'activity_summary'))
        """
    )
    op.execute(
        """
        CREATE POLICY training_load_daily_coach_read ON training_load_daily
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_athlete(athlete_id, 'training_load'))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS training_load_daily_coach_read ON training_load_daily")
    op.execute("DROP POLICY IF EXISTS completed_activities_coach_read ON completed_activities")
    op.execute("DROP POLICY IF EXISTS consent_grants_athlete_write ON consent_grants")
    op.execute("DROP POLICY IF EXISTS consent_grants_self_or_coach_read ON consent_grants")
    op.execute("DROP POLICY IF EXISTS team_memberships_athlete_update ON team_memberships")
    op.execute("DROP POLICY IF EXISTS team_memberships_self_or_coach_read ON team_memberships")
    op.execute("DROP POLICY IF EXISTS teams_member_read ON teams")
    op.execute("DROP FUNCTION IF EXISTS app_actor_can_read_athlete(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS app_team_primary_coach_name(uuid)")
    op.execute("DROP FUNCTION IF EXISTS app_actor_is_active_team_coach(uuid)")
    op.execute("DROP FUNCTION IF EXISTS app_actor_has_team_membership(uuid)")
    op.execute(
        "REVOKE SELECT, UPDATE ON team_memberships FROM runsense_runtime"
    )
    op.execute("REVOKE SELECT ON teams FROM runsense_runtime")
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON consent_grants FROM runsense_runtime")
    op.drop_column("users", "display_name")
    op.drop_table("consent_grants")
    op.drop_table("team_memberships")
    op.drop_table("teams")

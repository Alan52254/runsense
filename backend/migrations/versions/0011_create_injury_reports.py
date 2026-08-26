"""create split injury report storage

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "injury_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("athlete_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_mutation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("has_issue", sa.Boolean(), nullable=False),
        sa.Column("severity_band", sa.Text(), nullable=False),
        sa.Column("body_part", sa.Text(), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone_snapshot", sa.Text(), nullable=False),
        sa.Column("local_training_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("athlete_id", "client_mutation_id", name="uq_injury_reports_mutation"),
        sa.CheckConstraint(
            "severity_band IN ('NONE', 'MILD', 'MODERATE', 'SEVERE')",
            name="ck_injury_reports_severity",
        ),
        sa.CheckConstraint(
            "(has_issue AND severity_band <> 'NONE' AND body_part IS NOT NULL) OR "
            "(NOT has_issue AND severity_band = 'NONE' AND body_part IS NULL)",
            name="ck_injury_reports_consistent_issue",
        ),
    )
    op.create_index(
        "ix_injury_reports_athlete_date",
        "injury_reports",
        ["athlete_id", "local_training_date", "reported_at"],
    )
    op.create_table(
        "injury_report_details",
        sa.Column(
            "injury_report_id",
            UUID(as_uuid=True),
            sa.ForeignKey("injury_reports.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("free_text", sa.Text(), nullable=False),
    )

    op.execute("GRANT SELECT, INSERT ON injury_reports, injury_report_details TO runsense_runtime")
    for table in ("injury_reports", "injury_report_details"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE FUNCTION app_injury_report_owned_by_actor(target_report_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT EXISTS (
            SELECT 1 FROM injury_reports report
             WHERE report.id = target_report_id
               AND report.athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_actor_can_read_injury_detail(target_report_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT EXISTS (
            SELECT 1 FROM injury_reports report
             WHERE report.id = target_report_id
               AND app_actor_can_read_athlete(report.athlete_id, 'injury_detail')
          )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_latest_injury_detail_for_actor(target_athlete_id uuid)
        RETURNS text LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT detail.free_text
            FROM injury_reports report
            LEFT JOIN injury_report_details detail ON detail.injury_report_id = report.id
           WHERE report.athlete_id = target_athlete_id
             AND app_actor_can_read_athlete(target_athlete_id, 'injury_detail')
           ORDER BY report.reported_at DESC, report.id DESC
           LIMIT 1
        $$
        """
    )
    for signature in (
        "app_injury_report_owned_by_actor(uuid)",
        "app_actor_can_read_injury_detail(uuid)",
        "app_latest_injury_detail_for_actor(uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO runsense_runtime")

    op.execute(
        """
        CREATE POLICY injury_reports_self_read ON injury_reports
          FOR SELECT TO runsense_runtime
          USING (athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY injury_reports_self_insert ON injury_reports
          FOR INSERT TO runsense_runtime
          WITH CHECK (athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY injury_reports_coach_read ON injury_reports
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_athlete(athlete_id, 'injury_status'))
        """
    )
    op.execute(
        """
        CREATE POLICY injury_report_details_self_read ON injury_report_details
          FOR SELECT TO runsense_runtime
          USING (app_injury_report_owned_by_actor(injury_report_id))
        """
    )
    op.execute(
        """
        CREATE POLICY injury_report_details_self_insert ON injury_report_details
          FOR INSERT TO runsense_runtime
          WITH CHECK (app_injury_report_owned_by_actor(injury_report_id))
        """
    )
    op.execute(
        """
        CREATE POLICY injury_report_details_coach_read ON injury_report_details
          FOR SELECT TO runsense_runtime
          USING (app_actor_can_read_injury_detail(injury_report_id))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS injury_report_details_coach_read ON injury_report_details")
    op.execute("DROP POLICY IF EXISTS injury_report_details_self_insert ON injury_report_details")
    op.execute("DROP POLICY IF EXISTS injury_report_details_self_read ON injury_report_details")
    op.execute("DROP POLICY IF EXISTS injury_reports_coach_read ON injury_reports")
    op.execute("DROP POLICY IF EXISTS injury_reports_self_insert ON injury_reports")
    op.execute("DROP POLICY IF EXISTS injury_reports_self_read ON injury_reports")
    op.execute("DROP FUNCTION IF EXISTS app_latest_injury_detail_for_actor(uuid)")
    op.execute("DROP FUNCTION IF EXISTS app_actor_can_read_injury_detail(uuid)")
    op.execute("DROP FUNCTION IF EXISTS app_injury_report_owned_by_actor(uuid)")
    op.execute("REVOKE SELECT, INSERT ON injury_reports, injury_report_details FROM runsense_runtime")
    op.drop_table("injury_report_details")
    op.drop_index("ix_injury_reports_athlete_date", table_name="injury_reports")
    op.drop_table("injury_reports")

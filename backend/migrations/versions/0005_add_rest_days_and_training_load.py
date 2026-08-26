"""add athlete rest days and materialized training load

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _actor_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_actor_rw ON {table}
          TO runsense_runtime
          USING (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
          WITH CHECK (
            athlete_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
          )
        """
    )


def upgrade() -> None:
    op.create_table(
        "athlete_rest_days",
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("athlete_id", "date", name="pk_athlete_rest_days"),
    )
    op.create_table(
        "training_load_daily",
        sa.Column("athlete_id", UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("session_load", sa.Numeric(), nullable=False),
        sa.Column("source_metric", sa.Text(), nullable=False),
        sa.Column("acute_load", sa.Numeric(), nullable=False),
        sa.Column("chronic_load", sa.Numeric(), nullable=False),
        sa.Column("load_ratio", sa.Numeric(), nullable=True),
        sa.Column("data_quality", sa.Text(), nullable=False),
        sa.Column("observation_days", sa.SmallInteger(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint(
            "athlete_id", "date", "unit", name="pk_training_load_daily"
        ),
        sa.CheckConstraint(
            "unit <> '' AND source_metric <> ''", name="ck_training_load_daily_metric_names"
        ),
        sa.CheckConstraint(
            "session_load >= 0 AND session_load <> 'Infinity'::numeric "
            "AND session_load <> 'NaN'::numeric",
            name="ck_training_load_daily_session_load",
        ),
        sa.CheckConstraint(
            "acute_load >= 0 AND acute_load <> 'Infinity'::numeric "
            "AND acute_load <> 'NaN'::numeric",
            name="ck_training_load_daily_acute_load",
        ),
        sa.CheckConstraint(
            "chronic_load >= 0 AND chronic_load <> 'Infinity'::numeric "
            "AND chronic_load <> 'NaN'::numeric",
            name="ck_training_load_daily_chronic_load",
        ),
        sa.CheckConstraint(
            "load_ratio IS NULL OR (load_ratio >= 0 "
            "AND load_ratio <> 'Infinity'::numeric AND load_ratio <> 'NaN'::numeric)",
            name="ck_training_load_daily_ratio",
        ),
        sa.CheckConstraint(
            "data_quality IN ('SUFFICIENT', 'LOW', 'INSUFFICIENT')",
            name="ck_training_load_daily_quality",
        ),
        sa.CheckConstraint(
            "observation_days BETWEEN 0 AND 28",
            name="ck_training_load_daily_observations",
        ),
        sa.CheckConstraint(
            "algorithm_version <> '' AND schema_version > 0",
            name="ck_training_load_daily_versions",
        ),
        sa.CheckConstraint(
            "input_snapshot_hash ~ '^[0-9a-f]{64}$'",
            name="ck_training_load_daily_hash",
        ),
    )
    op.create_index(
        "ix_training_load_daily_athlete_date",
        "training_load_daily",
        ["athlete_id", "date"],
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON athlete_rest_days TO runsense_runtime"
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON training_load_daily TO runsense_runtime"
    )
    _actor_policy("athlete_rest_days")
    _actor_policy("training_load_daily")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS training_load_daily_actor_rw ON training_load_daily")
    op.execute("DROP POLICY IF EXISTS athlete_rest_days_actor_rw ON athlete_rest_days")
    op.execute(
        "REVOKE SELECT, INSERT, DELETE ON training_load_daily FROM runsense_runtime"
    )
    op.execute(
        "REVOKE SELECT, INSERT, DELETE ON athlete_rest_days FROM runsense_runtime"
    )
    op.drop_table("training_load_daily")
    op.drop_table("athlete_rest_days")

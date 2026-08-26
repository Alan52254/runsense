"""add structured workout segments to completed_activities

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-25

Mirrors 0013_add_assignment_structure.py's assigned_workouts.structure --
same JSON shape (a list of WorkoutSegment-like objects: kind, label,
distanceMeters, durationSeconds, repetitions, distancesMeters, pace,
restSeconds), same NOT NULL DEFAULT '[]' so existing rows and the
duration+RPE-only creation path both stay valid without a backfill.
Purely additive detail: duration_minutes/rpe remain the fields that drive
session_load, unaffected by whether structure is populated.
"""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completed_activities",
        sa.Column("structure", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("completed_activities", "structure")

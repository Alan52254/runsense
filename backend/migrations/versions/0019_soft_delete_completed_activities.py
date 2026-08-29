"""soft-delete support for completed_activities

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-26

The runtime role (runsense_runtime, see migration 0001) was deliberately
never granted DELETE on this table -- a Completed Activity is designed as
an immutable canonical record, not a row a client can make disappear
outright. An athlete still needs a way to remove a mistaken or unwanted
entry from their own history, so this adds deleted_at instead of a DELETE
grant: "removed" becomes a timestamp, not a missing row. Every read path
that lists or aggregates completed_activities (GET /activities, training
load computation, the coach roster's last-activity-date, and the
rest-day-conflict check) must filter deleted_at IS NULL -- see
routes/activities.py's delete_activity and the other call sites updated
alongside this migration.
"""

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completed_activities",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("completed_activities", "deleted_at")

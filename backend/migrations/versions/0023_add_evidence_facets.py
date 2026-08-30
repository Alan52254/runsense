"""add retrieval facets to reviewed guidance

Retrieval narrows by what the situation is -- body part, topic, recovery
phase -- before anything is scored. Without these columns every added source
competes on common words alone, so growing the library degrades precision.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evidence_passages",
        sa.Column(
            "body_parts",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "evidence_passages",
        sa.Column(
            "topics",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    # PROTECTION / LOADING / RETURN_TO_RUN, or NULL for stage-independent.
    op.add_column("evidence_passages", sa.Column("phase", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_evidence_passages_phase",
        "evidence_passages",
        "phase IS NULL OR phase IN ('PROTECTION', 'LOADING', 'RETURN_TO_RUN')",
    )
    # What a stage is for, and what would let the Athlete progress past it.
    op.add_column("evidence_passages", sa.Column("phase_purpose", sa.Text(), nullable=True))
    op.add_column(
        "evidence_passages", sa.Column("progression_criterion", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        "ck_evidence_passages_phase_is_explained",
        "evidence_passages",
        "phase IS NULL OR (phase_purpose IS NOT NULL AND progression_criterion IS NOT NULL)",
    )
    op.create_index(
        "ix_evidence_passages_body_parts",
        "evidence_passages",
        ["body_parts"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_passages_body_parts", table_name="evidence_passages")
    op.drop_constraint("ck_evidence_passages_phase_is_explained", "evidence_passages")
    op.drop_constraint("ck_evidence_passages_phase", "evidence_passages")
    op.drop_column("evidence_passages", "progression_criterion")
    op.drop_column("evidence_passages", "phase_purpose")
    op.drop_column("evidence_passages", "phase")
    op.drop_column("evidence_passages", "topics")
    op.drop_column("evidence_passages", "body_parts")

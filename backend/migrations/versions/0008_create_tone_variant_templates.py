"""create tone_variant_templates, seeded with the reviewed copy library

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_TABLE = sa.table(
    "tone_variant_templates",
    sa.column("tone_variant_id", sa.Text()),
    sa.column("text", sa.Text()),
    sa.column("reviewed_by", sa.Text()),
    sa.column("reviewed_at", sa.DateTime(timezone=True)),
)

# REQ-AI-006: the LLM may only ever select one of these ids — nothing else.
# Text migrated as-is from web/src/data/demoData.ts's toneVariants (see
# design.md Decision 8 for why this is a known, deliberate compromise
# against "human-reviewed" rather than a live review workflow).
_SEED_ROWS = [
    {
        "tone_variant_id": "SUPPORTIVE_A",
        "text": "最近幾週你把量堆起來了，今天照課表輕鬆跑就好，讓身體把訓練吸收進去。",
        "reviewed_by": "運動科學顧問 · 李念真",
        "reviewed_at": "2026-07-14T02:00:00.000Z",
    },
    {
        "tone_variant_id": "SUPPORTIVE_B",
        "text": "穩定累積比單日突破更重要，今天維持節奏就是好的一天。",
        "reviewed_by": "運動科學顧問 · 李念真",
        "reviewed_at": "2026-07-14T02:00:00.000Z",
    },
    {
        "tone_variant_id": "STEADY_A",
        "text": "課表照常，維持你目前的節奏。",
        "reviewed_by": "產品 · 何宛庭",
        "reviewed_at": "2026-07-14T02:00:00.000Z",
    },
    {
        "tone_variant_id": "CAUTION_A",
        "text": "你回報了身體不適，今天請以能輕鬆對話的強度為上限。",
        "reviewed_by": "運動科學顧問 · 李念真",
        "reviewed_at": "2026-07-14T02:00:00.000Z",
    },
    {
        "tone_variant_id": "NEUTRAL_FALLBACK",
        "text": "以下是今天的課表。",
        "reviewed_by": "系統預設",
        "reviewed_at": "2026-07-14T02:00:00.000Z",
    },
]


def upgrade() -> None:
    op.create_table(
        "tone_variant_templates",
        sa.Column("tone_variant_id", sa.Text(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("text <> ''", name="ck_tone_variant_templates_text"),
    )
    op.bulk_insert(_TABLE, _SEED_ROWS)
    # Read-only from the app's perspective — new variants are added by a
    # future migration after a real review pass, not by the runtime role.
    op.execute("GRANT SELECT ON tone_variant_templates TO runsense_runtime")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON tone_variant_templates FROM runsense_runtime")
    op.drop_table("tone_variant_templates")

"""create approved evidence graph

Revision ID: 0020
Revises: 0019
"""

from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_passages",
        sa.Column("evidence_id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("revision_date", sa.Date(), nullable=False),
        sa.Column("license_or_provenance", sa.Text(), nullable=False),
        sa.Column("corpus_version", sa.Text(), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("keywords", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "evidence_edges",
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey("evidence_passages.evidence_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_id",
            sa.Text(),
            sa.ForeignKey("evidence_passages.evidence_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("relationship", sa.Text(), nullable=False),
        sa.CheckConstraint("source_id <> target_id", name="ck_evidence_edge_not_self"),
    )
    passages = sa.table(
        "evidence_passages",
        sa.column("evidence_id", sa.Text()),
        sa.column("title", sa.Text()),
        sa.column("publisher", sa.Text()),
        sa.column("source_url", sa.Text()),
        sa.column("revision_date", sa.Date()),
        sa.column("license_or_provenance", sa.Text()),
        sa.column("corpus_version", sa.Text()),
        sa.column("text", sa.Text()),
        sa.column("keywords", sa.ARRAY(sa.Text())),
        sa.column("approved", sa.Boolean()),
    )
    op.bulk_insert(
        passages,
        [
            {
                "evidence_id": "aaos-stress-fracture-warning-signs",
                "title": "Stress Fractures of the Foot and Ankle",
                "publisher": "AAOS OrthoInfo",
                "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/stress-fractures-of-the-foot-and-ankle/",
                "revision_date": "2026-08-29",
                "license_or_provenance": "link-and-manually-authored-summary; source text not ingested",
                "corpus_version": "sports-medicine-v1",
                "text": "Localized bone pain that worsens with weight bearing should not be exercised through and needs prompt assessment.",
                "keywords": ["bone pain", "weight bearing", "stress fracture"],
                "approved": True,
            },
            {
                "evidence_id": "runsense-bone-stress-next-step",
                "title": "Conservative next step for a bone-stress pattern",
                "publisher": "RunSense reviewed guidance",
                "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/stress-fractures-of-the-foot-and-ankle/",
                "revision_date": "2026-08-29",
                "license_or_provenance": "human-reviewed guidance derived from linked source",
                "corpus_version": "sports-medicine-v1",
                "text": "Stop impact activity and arrange assessment by a qualified clinician.",
                "keywords": ["stop running", "clinician assessment"],
                "approved": True,
            },
        ],
    )
    op.execute(
        """
        INSERT INTO evidence_edges (source_id, target_id, relationship)
        VALUES ('aaos-stress-fracture-warning-signs',
                'runsense-bone-stress-next-step',
                'HAS_CONSERVATIVE_NEXT_STEP')
        """
    )
    op.execute("GRANT SELECT ON evidence_passages, evidence_edges TO runsense_runtime")


def downgrade() -> None:
    op.drop_table("evidence_edges")
    op.drop_index("ix_evidence_passages_corpus_version", table_name="evidence_passages")
    op.drop_table("evidence_passages")

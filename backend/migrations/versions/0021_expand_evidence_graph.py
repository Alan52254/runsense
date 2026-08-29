"""expand approved evidence graph with common running-injury passages

Revision ID: 0021
Revises: 0020

Adds bilingual keyword coverage (Chinese body-part terms + English) so graph
retrieval returns citations for everyday reports, plus a general
load-management / soreness passage used as a fallback when nothing else
matches. Every entry is link-and-manually-authored-summary provenance; no
third-party source text is ingested.
"""

from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


_PASSAGES = [
    {
        "evidence_id": "aaos-calf-strain-return-to-run",
        "title": "Muscle Strains in the Thigh / Calf",
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/muscle-strains-in-the-thigh/",
        "text": "Grade I calf or hamstring strains are managed with relative rest, "
        "then a gradual return once walking and easy jogging are pain-free.",
        "keywords": ["小腿", "大腿後", "腿後", "calf", "hamstring", "strain"],
    },
    {
        "evidence_id": "aaos-runners-knee-load-management",
        "title": "Patellofemoral Pain Syndrome (Runner's Knee)",
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/patellofemoral-pain-syndrome/",
        "text": "Anterior knee pain that eases with activity modification usually "
        "responds to reduced mileage, pain-free cross-training, and hip / quad strengthening.",
        "keywords": ["膝", "knee", "patellofemoral", "runner's knee"],
    },
    {
        "evidence_id": "aaos-achilles-tendinopathy-first-steps",
        "title": "Achilles Tendinitis",
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/achilles-tendinitis/",
        "text": "Mid-portion Achilles tendinopathy is managed with load reduction and "
        "progressive calf loading; sudden spikes in hill or speed work are avoided.",
        "keywords": ["阿基里斯", "跟腱", "achilles", "tendinopathy", "tendinitis"],
    },
    {
        "evidence_id": "aaos-plantar-fasciitis-self-care",
        "title": "Plantar Fasciitis and Bone Spurs",
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/plantar-fasciitis-and-bone-spurs/",
        "text": "Plantar heel pain that is worst with the first steps of the day "
        "responds to calf and plantar-fascia stretching, supportive shoes, and reduced impact volume.",
        "keywords": ["足底", "腳底", "足跟", "plantar", "heel pain", "fasciitis"],
    },
    {
        "evidence_id": "aaos-shin-splints-conservative",
        "title": "Shin Splints (Medial Tibial Stress Syndrome)",
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/shin-splints/",
        "text": "Diffuse shin pain along the inner border of the tibia is managed with "
        "a temporary drop in running volume and a gradual, low-impact build-back; focal bone "
        "tenderness is treated as possible bone stress instead.",
        "keywords": ["脛", "小腿前", "shin", "tibial", "shin splints"],
    },
    {
        "evidence_id": "acsm-low-back-running",
        "title": "Low Back Pain and Physical Activity",
        "publisher": "American College of Sports Medicine",
        "source_url": "https://www.acsm.org/",
        "text": "Non-radiating mechanical low-back pain generally does not require stopping "
        "activity; staying active within comfort and avoiding prolonged rest is favoured.",
        "keywords": ["下背", "腰", "low back", "lumbar", "back pain"],
    },
    {
        "evidence_id": "aaos-hip-glute-tendinopathy",
        "title": "Hip Pain in the Active Adult",
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/",
        "text": "Lateral hip / gluteal tendon pain is aggravated by rapid mileage increases "
        "and hill running; a short deload with isometric gluteal loading is the usual first step.",
        "keywords": ["髖", "臀", "hip", "glute", "gluteal"],
    },
    {
        "evidence_id": "runsense-general-load-management",
        "title": "General load management for a new niggle",
        "publisher": "RunSense reviewed guidance",
        "source_url": "https://orthoinfo.aaos.org/en/staying-healthy/",
        "text": "For a mild, non-alarming niggle: keep the next few days easy, hold weekly "
        "mileage flat rather than increasing it, and stop the run if pain rises above a mild ache "
        "or changes your gait.",
        "keywords": ["__general__", "niggle", "soreness", "痠", "痛"],
    },
    {
        "evidence_id": "runsense-when-to-see-a-clinician",
        "title": "When a running niggle needs a clinician",
        "publisher": "RunSense reviewed guidance",
        "source_url": "https://orthoinfo.aaos.org/en/staying-healthy/",
        "text": "Seek assessment for pain that wakes you at night, focal bone tenderness, "
        "swelling that does not settle in a few days, or any symptom that is getting worse "
        "week to week despite easing off.",
        "keywords": ["__general__", "clinician", "assessment", "就醫", "惡化"],
    },
]

_EDGES = [
    ("aaos-calf-strain-return-to-run", "runsense-general-load-management", "HAS_CONSERVATIVE_NEXT_STEP"),
    ("aaos-runners-knee-load-management", "runsense-general-load-management", "HAS_CONSERVATIVE_NEXT_STEP"),
    ("aaos-achilles-tendinopathy-first-steps", "runsense-general-load-management", "HAS_CONSERVATIVE_NEXT_STEP"),
    ("aaos-plantar-fasciitis-self-care", "runsense-general-load-management", "HAS_CONSERVATIVE_NEXT_STEP"),
    ("aaos-shin-splints-conservative", "aaos-stress-fracture-warning-signs", "ESCALATES_TO"),
    ("acsm-low-back-running", "runsense-when-to-see-a-clinician", "ESCALATES_TO"),
    ("aaos-hip-glute-tendinopathy", "runsense-general-load-management", "HAS_CONSERVATIVE_NEXT_STEP"),
]


def upgrade() -> None:
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
                **row,
                "revision_date": "2026-08-29",
                "license_or_provenance": "link-and-manually-authored-summary; source text not ingested",
                "corpus_version": "sports-medicine-v1",
                "approved": True,
            }
            for row in _PASSAGES
        ],
    )
    for source_id, target_id, relationship in _EDGES:
        op.execute(
            sa.text(
                "INSERT INTO evidence_edges (source_id, target_id, relationship) "
                "VALUES (:s, :t, :r)"
            ).bindparams(s=source_id, t=target_id, r=relationship)
        )


def downgrade() -> None:
    ids = tuple(row["evidence_id"] for row in _PASSAGES)
    op.execute(
        sa.text("DELETE FROM evidence_edges WHERE source_id IN :ids OR target_id IN :ids")
        .bindparams(sa.bindparam("ids", value=ids, expanding=True))
    )
    op.execute(
        sa.text("DELETE FROM evidence_passages WHERE evidence_id IN :ids")
        .bindparams(sa.bindparam("ids", value=ids, expanding=True))
    )

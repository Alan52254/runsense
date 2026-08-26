"""add athlete_profiles.sex

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-25

Needed so /weather can select the correct sex-specific speed-loss curve
(see app/weather_pace.py) -- the underlying research (El Helou et al. 2012,
PLOS ONE, Table S3) only reports separate coefficients for men and women,
so an athlete who hasn't set this yet gets the sex-neutral average curve
rather than a guess.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("athlete_profiles", sa.Column("sex", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_athlete_profiles_sex", "athlete_profiles", "sex IN ('male', 'female')"
    )
    # athlete_profiles already has a table-wide UPDATE grant from 0006; no
    # new GRANT needed for this column.


def downgrade() -> None:
    op.drop_constraint("ck_athlete_profiles_sex", "athlete_profiles", type_="check")
    op.drop_column("athlete_profiles", "sex")

"""Admin command for rebuilding materialized Training Load Trend rows.

Run explicitly after migration; this module is never imported by application
startup. It uses the same bounded recomputation interface as live mutations.
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy import create_engine, text

from app.db import actor_transaction
from app.training_load_store import recompute_training_load


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_engine(database_url, future=True)
    with engine.connect() as conn:
        role = conn.execute(
            text(
                "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname=current_user"
            )
        ).one()
        if not (role.rolsuper or role.rolbypassrls):
            raise RuntimeError(
                "backfill requires an admin DATABASE_URL whose role is SUPERUSER "
                "or BYPASSRLS; a runtime role would silently miss other athletes"
            )
        inputs = conn.execute(
            text(
                "SELECT athlete_id,input_date FROM ("
                "SELECT athlete_id,local_training_date AS input_date FROM completed_activities "
                "UNION SELECT athlete_id,date AS input_date FROM athlete_rest_days"
                ") canonical_inputs ORDER BY athlete_id,input_date"
            )
        ).all()
        conn.rollback()
        for athlete_id, input_date in inputs:
            with actor_transaction(conn, str(athlete_id)) as tx:
                recompute_training_load(tx, uuid.UUID(str(athlete_id)), input_date)
    engine.dispose()
    print(f"recomputed {len(inputs)} distinct athlete/date inputs")


if __name__ == "__main__":
    main()

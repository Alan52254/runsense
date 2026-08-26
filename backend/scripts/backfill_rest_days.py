"""Mark every day without a Completed Activity, within one athlete's tracked
history, as a confirmed Rest Day -- so training_load's data_quality/
observation_days counts them as "observed" instead of "no data".

Run manually from backend/; application code never imports this module.
Idempotent: ON CONFLICT DO NOTHING, safe to re-run.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from app.training_load_store import lock_athlete_training_load, recompute_training_load

_SELECT_ACTIVITY_DATES = text(
    "SELECT DISTINCT local_training_date FROM completed_activities WHERE athlete_id = :athlete_id"
)
_UPSERT_REST = text(
    "INSERT INTO athlete_rest_days (athlete_id, date) VALUES (:athlete_id, :date) "
    "ON CONFLICT (athlete_id, date) DO NOTHING"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="runner.tokyo@runsense.demo")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            athlete_id = conn.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": args.email}
            ).scalar_one_or_none()
            if athlete_id is None:
                raise RuntimeError(f"No user found for {args.email}")

            activity_dates = {
                row.local_training_date
                for row in conn.execute(_SELECT_ACTIVITY_DATES, {"athlete_id": athlete_id})
            }
            if not activity_dates:
                print(f"No activities found for {args.email} -- nothing to bound the backfill range with.")
                return

            start = min(activity_dates)
            # Never preemptively mark today as rest -- the athlete may still
            # train today. Backfill only strictly-past days.
            end = date.today() - timedelta(days=1)

            lock_athlete_training_load(conn, athlete_id)

            inserted = 0
            d = start
            while d <= end:
                if d not in activity_dates:
                    result = conn.execute(_UPSERT_REST, {"athlete_id": athlete_id, "date": d})
                    inserted += result.rowcount
                d += timedelta(days=1)

            print(f"Backfilled {inserted} rest days for {args.email} ({start} to {end}).")

            recompute_training_load(conn, athlete_id, end - timedelta(days=27))
    finally:
        engine.dispose()

    print("Done.")


if __name__ == "__main__":
    main()

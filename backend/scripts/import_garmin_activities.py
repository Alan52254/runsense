"""Import running activities from a Garmin Connect "Export Your Data" GDPR
archive into one demo persona's Completed Activities history.

Run manually from backend/; application code never imports this module.

Garmin's export includes a single JSON file
(DI_CONNECT/DI-Connect-Fitness/<email>_1_summarizedActivities.json) with one
entry per activity, each carrying a `splits` array (lap-level detail: pace,
heart rate, elevation, cadence per lap) and a `workoutRpe` field -- the
athlete's own self-reported exertion on Garmin's 0-100 scale.

RunSense's only activity-creation path, POST /activities (see
app/routes/activities.py), stores just duration_minutes + rpe (1-10) + when
it happened -- there is no distance/pace/HR/lap column on
completed_activities today, so this script necessarily discards the richer
per-lap detail rather than inventing a schema for it. workoutRpe/10
(clamped, rounded) becomes RunSense's rpe -- a real self-reported number,
not a synthesized one. The ~1% of activities missing workoutRpe are skipped
rather than backfilled with a fabricated value.

Idempotent: client_mutation_id is uuid5-derived from Garmin's own
activityId, so re-running this script only ever inserts each activity once
(ON CONFLICT DO NOTHING), matching the existing users/athlete_profiles
pattern in seed_demo_personas.py.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from app.training_load_store import lock_athlete_training_load, recompute_training_load

_RUNNING_ACTIVITY_TYPES = {"running", "track_running", "treadmill_running", "trail_running"}

# The synthetic 8-activity seed from seed_demo_personas.py's
# _seed_sample_activities -- once real Garmin history exists for an athlete,
# those placeholder rows would double-count against real runs on nearby
# dates, inflating the acute/chronic numbers. Deleted for the target
# athlete only, matched by the same client_mutation_id derivation that
# script uses, so this never touches any other athlete's data.
_DEMO_SEED_MUTATION_NAMESPACE = "runsense-demo-seed"

_INSERT_ACTIVITY = text(
    """
    INSERT INTO completed_activities (
        athlete_id, client_mutation_id, request_fingerprint,
        duration_minutes, rpe, performed_at,
        timezone_snapshot, local_training_date, session_load
    ) VALUES (
        :athlete_id, :client_mutation_id, :request_fingerprint,
        :duration_minutes, :rpe, :performed_at,
        :timezone_snapshot, :local_training_date, :session_load
    )
    ON CONFLICT (athlete_id, client_mutation_id) DO NOTHING
    """
)


def _load_summarized_activities(zip_path: Path) -> list[dict]:
    """The export is a zip-of-zips: the top-level GDPR archive contains
    DI_CONNECT/DI-Connect-Fitness/*_1_summarizedActivities.json directly
    (not itself zipped), unlike the raw per-activity .fit files which sit
    inside a further-nested UploadedFiles*.zip this script doesn't need."""
    with zipfile.ZipFile(zip_path) as archive:
        matches = [
            n for n in archive.namelist() if n.endswith("_1_summarizedActivities.json")
        ]
        if not matches:
            raise RuntimeError(f"No *_1_summarizedActivities.json found in {zip_path}")
        with archive.open(matches[0]) as f:
            data = json.load(f)
    return data[0]["summarizedActivitiesExport"]


def _to_rpe(workout_rpe: float | None) -> int | None:
    """Garmin's 0-100 self-reported exertion scale -> RunSense's 1-10.
    None (the ~1% of activities without a self-reported value) means
    "skip this activity" -- see the module docstring for why this isn't
    backfilled with a guess."""
    if workout_rpe is None:
        return None
    return max(1, min(10, round(workout_rpe / 10)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path, help="Path to the Garmin GDPR export zip")
    parser.add_argument("--email", default="runner.tokyo@runsense.demo")
    parser.add_argument("--timezone", default="Asia/Tokyo")
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and report counts without writing to the DB"
    )
    args = parser.parse_args()

    activities = _load_summarized_activities(args.zip_path)
    runs = [a for a in activities if a.get("activityType") in _RUNNING_ACTIVITY_TYPES]
    runs.sort(key=lambda a: a.get("beginTimestamp") or 0)

    tzinfo = ZoneInfo(args.timezone)
    rows = []
    skipped_no_rpe = 0
    for activity in runs:
        rpe = _to_rpe(activity.get("workoutRpe"))
        if rpe is None:
            skipped_no_rpe += 1
            continue
        duration_minutes = Decimal(str((activity.get("duration") or 0) / 1000 / 60))
        if duration_minutes <= 0:
            continue
        performed_at = datetime.fromtimestamp(activity["beginTimestamp"] / 1000, tz=timezone.utc)
        local_training_date = performed_at.astimezone(tzinfo).date()
        client_mutation_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"garmin-import:{args.email}:{activity['activityId']}"
        )
        rows.append(
            {
                "client_mutation_id": client_mutation_id,
                "request_fingerprint": f"garmin-import:{client_mutation_id}",
                "duration_minutes": duration_minutes,
                "rpe": rpe,
                "performed_at": performed_at,
                "timezone_snapshot": args.timezone,
                "local_training_date": local_training_date,
                "session_load": duration_minutes * rpe,
            }
        )

    print(f"Parsed {len(runs)} running-type activities, {len(rows)} importable, {skipped_no_rpe} skipped (no workoutRpe).")
    if rows:
        print(f"Date range: {rows[0]['local_training_date']} to {rows[-1]['local_training_date']}")

    if args.dry_run:
        print("Dry run -- no database changes made.")
        return

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
                raise RuntimeError(f"No user found for {args.email} -- run seed_demo_personas.py first")

            lock_athlete_training_load(conn, athlete_id)

            deleted = conn.execute(
                text(
                    "DELETE FROM completed_activities "
                    "WHERE athlete_id = :athlete_id AND request_fingerprint LIKE 'demo-seed:%'"
                ),
                {"athlete_id": athlete_id},
            ).rowcount
            if deleted:
                print(f"Removed {deleted} synthetic demo-seed activities for {args.email} to avoid double-counting.")

            inserted = 0
            for row in rows:
                result = conn.execute(_INSERT_ACTIVITY, {"athlete_id": athlete_id, **row})
                inserted += result.rowcount
            print(f"Inserted {inserted} new activities ({len(rows) - inserted} already present, unchanged).")

            today = datetime.now(timezone.utc).date()
            recompute_training_load(conn, athlete_id, today - timedelta(days=27))
    finally:
        engine.dispose()

    print("Done.")


if __name__ == "__main__":
    main()

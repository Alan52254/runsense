"""Turn the workouts athletes wrote into their Garmin activity names into
structured prescriptions ("課表要求", source = activity_name).

Run manually from backend/ after import_garmin_fit_telemetry.py:

    python scripts/generate_workout_prescriptions.py ../dataset/<export>.zip

1. stores each activity's Garmin name on activity_telemetry.activity_name
   (matched on provider_activity_id = Garmin activityId);
2. for every name that reads like a workout ("400 x 10 組休1分鐘 84/圈",
   "2000 1600 1200 800") the language model turns it into blocks of reps
   with per-rep targets and recoveries; app/workout_prescription.py rejects
   any result containing a number that is not in the name;
3. saves it as the activity's prescription unless the athlete has already
   entered one themselves.

Sessions without such a name need nothing stored: their prescription is
inferred from the run on the fly (and labelled as inferred). Groq's free
tier rate limit is waited out, so expect roughly one name per few seconds.
Idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime_env import load_runtime_environment  # noqa: E402
from app.workout_prescription import looks_like_workout, parse_text  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--email", default="runner.tokyo@runsense.demo")
    args = parser.parse_args()
    load_runtime_environment()

    with zipfile.ZipFile(args.zip_path) as archive:
        name = next(n for n in archive.namelist() if n.endswith("_1_summarizedActivities.json"))
        acts = json.load(archive.open(name))[0]["summarizedActivitiesExport"]
    names = {str(a["activityId"]): (a.get("name") or "").strip() for a in acts}

    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    try:
        with engine.begin() as conn:
            athlete_id = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": args.email}).scalar_one()
            rows = conn.execute(
                text("SELECT a.id, a.provider_activity_id FROM completed_activities a "
                     "JOIN activity_telemetry t ON t.activity_id = a.id WHERE a.athlete_id = :a"),
                {"a": athlete_id},
            ).all()
            for r in rows:
                conn.execute(text("UPDATE activity_telemetry SET activity_name = :n WHERE activity_id = :id"),
                             {"n": names.get(str(r.provider_activity_id)), "id": r.id})
            athlete_entered = set(conn.execute(
                text("SELECT activity_id FROM workout_prescriptions WHERE athlete_id = :a AND source = 'athlete_text'"),
                {"a": athlete_id}).scalars().all())
        print(f"Stored names for {len(rows)} activities.")

        todo = [(r.id, names.get(str(r.provider_activity_id))) for r in rows
                if looks_like_workout(names.get(str(r.provider_activity_id))) and r.id not in athlete_entered]
        print(f"{len(todo)} names read like a workout; parsing...")
        saved = rejected = 0
        for activity_id, activity_name in todo:
            result = parse_text(activity_name, deadline_s=90)
            p = result["prescription"]
            if p is None:
                rejected += 1
                print(f"  skip  {activity_name!r}: {'; '.join(result['problems'])}")
                continue
            p["source"] = "activity_name"
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO workout_prescriptions (activity_id, athlete_id, source, raw_text, prescription)
                        VALUES (:id, :a, 'activity_name', :raw, CAST(:p AS jsonb))
                        ON CONFLICT (activity_id) DO UPDATE SET raw_text = EXCLUDED.raw_text,
                            prescription = EXCLUDED.prescription, updated_at = now()
                        WHERE workout_prescriptions.source = 'activity_name'
                        """
                    ),
                    {"id": activity_id, "a": athlete_id, "raw": activity_name, "p": json.dumps(p)},
                )
            saved += 1
            print(f"  ok    {activity_name!r} -> {p['title']}")
        print(f"Saved {saved} prescriptions from activity names ({rejected} not usable).")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

"""Store the same-workout history numbers (workout_analysis.history_summary)
on every activity that was imported before they existed -- and, with
--redetect, refresh the import-time structure detection after a change to
app/workout_segmentation.py.

Run manually from backend/ (application code never imports this module):

    python scripts/backfill_history_metrics.py [--email runner.tokyo@runsense.demo] [--redetect] [--dry-run]

The analysis compares a session with the athlete's own earlier sessions of
the same workout (workout_analysis.usual_range). A session the athlete has
not analysed contributes its import-time detection; this re-runs the
analysis on that detection -- exactly what import_garmin_fit_telemetry.py
does at import -- and merges the result into activity_telemetry.
auto_summary. --redetect first re-runs the detection itself and rewrites
auto_detection and the activity's `structure`, as the importer does.
Analyses the athlete confirmed are not touched. Idempotent: safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.activity_structure import structure_from_detection  # noqa: E402
from app.workout_analysis import analyse_workout, history_summary, resolve_hr_profile  # noqa: E402
from app.workout_segmentation import detect_workout  # noqa: E402

_KIND_TO_SESSION = {"intervals": "intervals", "tempo": "tempo", "continuous": "easy"}

_IDS = text(
    """SELECT t.activity_id, t.athlete_id, t.auto_summary
         FROM activity_telemetry t
         JOIN completed_activities a ON a.id = t.activity_id
         JOIN users u ON u.id = t.athlete_id
        WHERE a.deleted_at IS NULL AND (t.auto_detection IS NOT NULL OR :redetect)
          AND (CAST(:email AS text) IS NULL OR u.email = :email)""")
_ROW = text(
    """SELECT t.sport, t.sub_sport, t.hr_profile, t.laps, t.timer_events, t.workout_steps, t.samples,
              t.auto_detection, a.local_training_date
         FROM activity_telemetry t JOIN completed_activities a ON a.id = t.activity_id
        WHERE t.activity_id = :id""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", default=None, help="only this athlete")
    parser.add_argument("--redetect", action="store_true", help="re-run structure detection first")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        ids = conn.execute(_IDS, {"email": args.email, "redetect": args.redetect}).all()
        # each athlete's easy pace, as the importer computes it: median moving
        # speed of their continuous runs
        easy: dict = {}
        for r in ids:
            s = r.auto_summary or {}
            if s.get("kind") == "continuous" and s.get("moving_median_speed"):
                easy.setdefault(r.athlete_id, []).append(s["moving_median_speed"])
        easy_speed = {a: statistics.median(v) for a, v in easy.items()}
        updated = redetected = changed = 0
        for k, ref in enumerate(ids, 1):
            r = conn.execute(_ROW, {"id": ref.activity_id}).first()
            tele = {"sport": r.sport, "sub_sport": r.sub_sport, "hr_profile": r.hr_profile, "laps": r.laps,
                    "timer_events": r.timer_events, "workout_steps": r.workout_steps, "samples": r.samples}
            speed = easy_speed.get(ref.athlete_id)
            detection = r.auto_detection or {}
            if args.redetect:
                fresh = detect_workout(tele, speed)
                changed += fresh.get("segments") != detection.get("segments")
                detection = fresh
                redetected += 1
            summary = {"kind": detection.get("kind"), "signature": detection.get("signature"),
                       "confidence": detection.get("confidence")}
            analysis = None
            if detection.get("segments"):
                hr = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=r.hr_profile,
                                        history_peak_30s=None, birth_year=None, on_date=r.local_training_date)
                analysis = analyse_workout(tele, detection["segments"],
                                           session_type=_KIND_TO_SESSION.get(detection.get("kind"), "other"),
                                           target_pace_s_per_km=None, hr=hr, easy_speed=speed)
                summary.update(history_summary(analysis["summary"]))
                updated += 1
            if not args.dry_run:
                conn.execute(
                    text("UPDATE activity_telemetry SET auto_summary = COALESCE(auto_summary, '{}'::jsonb) "
                         "|| CAST(:s AS jsonb)" + (", auto_detection = CAST(:d AS jsonb)" if args.redetect else "")
                         + " WHERE activity_id = :id"),
                    {"s": json.dumps(summary), "d": json.dumps(detection), "id": ref.activity_id})
                if args.redetect and analysis is not None:
                    conn.execute(
                        text("UPDATE completed_activities SET structure = CAST(:s AS jsonb) WHERE id = :id"),
                        {"s": json.dumps(structure_from_detection(analysis, detection)), "id": ref.activity_id})
            if k % 100 == 0:
                print(f"  {k}/{len(ids)}", flush=True)
    verb = "would get" if args.dry_run else "now have"
    print(f"{updated} of {len(ids)} activities {verb} history metrics."
          + (f" Re-detected {redetected}; detected segments changed on {changed}." if args.redetect else ""))


if __name__ == "__main__":
    main()

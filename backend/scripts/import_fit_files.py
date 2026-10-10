"""Import single Garmin activity files (.fit, or the .zip that Garmin
Connect's "Export Original" downloads) into one athlete's history.

Run manually from backend/:

    python scripts/import_fit_files.py <folder> [--email runner.tokyo@runsense.demo]

The counterpart of import_garmin_fit_telemetry.py for activities recorded
after a full Garmin export: everything comes from the .fit file itself --
duration, distance, heart rate, cadence, the athlete's own post-run RPE
(Garmin's 0-100 "workout_rpe", stored as 1-10), and the full per-second
telemetry. Activity names are not in .fit files, so a workout written into
a Garmin activity name is not available here.

Duplicate downloads (the same activity twice) and activities already in
the athlete's history (same start second) are skipped. An activity without
a self-reported RPE is skipped, as in the full import: session load is
duration x RPE and there is no honest value to put there.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import uuid
import zipfile
from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.fit_telemetry import FitParseError, parse_fit, peak_rolling_hr  # noqa: E402
from app.training_load_store import lock_athlete_training_load, recompute_training_load  # noqa: E402
from app.workout_analysis import analyse_workout, resolve_hr_profile  # noqa: E402
from app.workout_segmentation import detect_workout  # noqa: E402
from import_garmin_fit_telemetry import (  # noqa: E402
    _KIND_TO_SESSION,
    _UPSERT_ACTIVITY,
    _UPSERT_TELEMETRY,
    _moving_median_speed,
    structure_from_detection,
)


def _fit_payloads(folder: Path):
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() == ".fit":
            yield path.name, path.read_bytes()
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if name.lower().endswith(".fit"):
                        yield path.name, z.read(name)


def _activity_id_from(name: str) -> str | None:
    m = re.match(r"(\d{6,})", name)
    return m.group(1) if m else None


def _device_metrics(session: dict) -> dict:
    m: dict = {}
    if session.get("avg_hr"):
        m["avgHeartRate"] = round(session["avg_hr"])
    if session.get("max_hr"):
        m["maxHeartRate"] = round(session["max_hr"])
    if session.get("avg_cadence"):
        m["avgCadenceStepsPerMin"] = round(session["avg_cadence"] * 2)  # FIT: strides/min per foot
    if session.get("max_cadence"):
        m["maxCadenceStepsPerMin"] = round(session["max_cadence"] * 2)
    if session.get("ascent_m") is not None:
        m["elevationGainM"] = round(float(session["ascent_m"]), 1)
    if session.get("descent_m") is not None:
        m["elevationLossM"] = round(float(session["descent_m"]), 1)
    if session.get("calories"):
        m["calories"] = round(session["calories"])
    if session.get("aerobic_te") is not None:
        m["aerobicTrainingEffect"] = round(float(session["aerobic_te"]), 1)
    if session.get("anaerobic_te") is not None:
        m["anaerobicTrainingEffect"] = round(float(session["anaerobic_te"]), 1)
    return m


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--email", default="runner.tokyo@runsense.demo")
    parser.add_argument("--timezone", default="Asia/Taipei")
    args = parser.parse_args()
    tz = ZoneInfo(args.timezone)

    teles: dict[int, tuple[str, dict]] = {}
    for fname, data in _fit_payloads(args.folder):
        try:
            tele = parse_fit(data)
        except FitParseError as exc:
            print(f"  skip  {fname}: {exc}")
            continue
        if tele["sport"] != "running":
            print(f"  skip  {fname}: not a run ({tele['sport']})")
            continue
        key = int(tele["start_time"].timestamp())
        if key in teles:
            print(f"  skip  {fname}: duplicate of {teles[key][0]}")
            continue
        teles[key] = (fname, tele)
    print(f"{len(teles)} distinct runs in {args.folder}")

    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    try:
        with engine.begin() as conn:
            athlete_id = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": args.email}).scalar_one()
            existing = {int(t.timestamp()) for t in conn.execute(
                text("SELECT performed_at FROM completed_activities WHERE athlete_id = :a AND deleted_at IS NULL"),
                {"a": athlete_id}).scalars().all()}
            speeds = [s for s in conn.execute(
                text("SELECT (auto_summary->>'moving_median_speed')::float FROM activity_telemetry "
                     "WHERE athlete_id = :a AND auto_summary->>'kind' = 'continuous'"), {"a": athlete_id}).scalars().all()
                if s]
            easy_speed = statistics.median(speeds) if speeds else None
            lock_athlete_training_load(conn, athlete_id)

            imported, dates = 0, []
            for key, (fname, tele) in sorted(teles.items()):
                if key in existing:
                    print(f"  skip  {fname}: already in history")
                    continue
                s = tele["session"]
                if s.get("workout_rpe") is None:
                    print(f"  skip  {fname}: no self-reported RPE")
                    continue
                rpe = max(1, min(10, round(s["workout_rpe"] / 10)))
                duration = Decimal(str(round((s.get("timer_s") or s.get("elapsed_s") or 0) / 60, 4)))
                if duration <= 0:
                    continue
                performed_at = tele["start_time"].astimezone(timezone.utc)
                local_date = performed_at.astimezone(tz).date()
                provider_id = _activity_id_from(fname) or f"fit-{key}"
                cmid = uuid.uuid5(uuid.NAMESPACE_URL, f"garmin-import:{args.email}:{provider_id}")
                activity_id = conn.execute(_UPSERT_ACTIVITY, {
                    "athlete_id": athlete_id, "client_mutation_id": cmid,
                    "request_fingerprint": f"garmin-import:{cmid}", "provider_activity_id": provider_id,
                    "duration_minutes": duration, "rpe": rpe, "performed_at": performed_at,
                    "timezone_snapshot": args.timezone, "local_training_date": local_date,
                    "session_load": duration * rpe,
                    "distance_km": round(s["distance_m"] / 1000, 2) if s.get("distance_m") else None,
                    "device_metrics": json.dumps(_device_metrics(s)),
                }).scalar_one()
                conn.execute(_UPSERT_TELEMETRY, {
                    "activity_id": activity_id, "athlete_id": athlete_id, "sport": tele["sport"],
                    "sub_sport": tele["sub_sport"], "device": tele["device"],
                    "hr_profile": json.dumps(tele["hr_profile"]), "laps": json.dumps(tele["laps"]),
                    "timer_events": json.dumps(tele["timer_events"]),
                    "workout_steps": json.dumps(tele["workout_steps"]),
                    "samples": json.dumps(tele["samples"]), "hr_peak_30s": peak_rolling_hr(tele["samples"]),
                    "activity_name": None,
                })
                detection = detect_workout(tele, easy_speed)
                summary = {"kind": detection["kind"], "signature": detection["signature"],
                           "confidence": detection["confidence"], "moving_median_speed": _moving_median_speed(tele)}
                if detection["segments"]:
                    hr = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=tele["hr_profile"],
                                            history_peak_30s=None, birth_year=None, on_date=local_date)
                    analysis = analyse_workout(tele, detection["segments"],
                                               session_type=_KIND_TO_SESSION.get(detection["kind"], "other"),
                                               target_pace_s_per_km=None, hr=hr, easy_speed=easy_speed)
                    summ = analysis["summary"]
                    summary.update({
                        "mean_pace_s_per_km": summ.get("mean_work_pace_s_per_km") or summ.get("split_mean_pace_s_per_km"),
                        "mean_rep_hr": summ.get("mean_rep_hr"), "rep_count": summ.get("rep_count"),
                    })
                    conn.execute(text("UPDATE completed_activities SET structure = CAST(:s AS jsonb) WHERE id = :id"),
                                 {"s": json.dumps(structure_from_detection(analysis, detection)), "id": activity_id})
                conn.execute(text("UPDATE activity_telemetry SET auto_detection = CAST(:d AS jsonb), "
                                  "auto_summary = CAST(:s AS jsonb) WHERE activity_id = :id"),
                             {"d": json.dumps(detection), "s": json.dumps(summary), "id": activity_id})
                dates.append(local_date)
                imported += 1
                print(f"  ok    {fname}: {performed_at.astimezone(tz):%Y-%m-%d %H:%M} "
                      f"{(s.get('distance_m') or 0) / 1000:.2f} km RPE {rpe} -> {detection['signature']}")

            if dates:
                day = min(dates)
                last = max(dates)
                while day <= last + timedelta(days=27):
                    recompute_training_load(conn, athlete_id, day)
                    day += timedelta(days=28)
            print(f"Imported {imported} runs.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

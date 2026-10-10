"""Import a Garmin "Export Your Data" archive as one demo athlete's real
training history, replacing that athlete's synthetic demo activities.

Run manually from backend/ (application code never imports this module):

    python scripts/import_garmin_fit_telemetry.py ../dataset/<export>.zip

For every running activity in the export this script:

1. upserts the Completed Activity from the export's summarizedActivities
   file (duration, the athlete's own self-reported RPE, distance, device
   metrics, provider='garmin' + the real Garmin activityId) -- the same
   client_mutation_id derivation as import_garmin_activities.py, so it is
   safe to run on top of an earlier import;
2. finds that activity's original .fit file inside the export's nested
   UploadedFiles*.zip (matched on the exact start second) and stores its
   per-second telemetry, laps, pause/resume events and HR settings in
   activity_telemetry (see app/fit_telemetry.py);
3. runs workout-structure detection (app/workout_segmentation.py) against
   the athlete's own easy pace, caches it, and rewrites the activity's
   `structure` from it so History's workout-structure view and the
   AI analysis agree.

Synthetic rows for the athlete (demo-seed / rich-seed / tokyo-gapfill /
synthetic-garmin) are deleted: they would double-count against real runs
in the training-load window, and the point of this import is that nothing
on the athlete's History is made up. Activities without a self-reported
RPE (~1%) are skipped, as in import_garmin_activities.py: session load is
duration x RPE and there is no honest value to put there.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fit_telemetry import FitParseError, parse_fit, peak_rolling_hr  # noqa: E402
from app.training_load_store import lock_athlete_training_load, recompute_training_load  # noqa: E402
from app.workout_analysis import analyse_workout, fmt_pace, resolve_hr_profile  # noqa: E402
from app.workout_segmentation import MOVING_SPEED, build_grid, detect_workout  # noqa: E402

_RUNNING_TYPES = {"running", "track_running", "treadmill_running", "trail_running"}
_SYNTHETIC_PREFIXES = ("demo-seed:%", "rich-seed:%", "tokyo-gapfill:%", "synthetic-garmin:%")
_KIND_TO_SESSION = {"intervals": "intervals", "tempo": "tempo", "continuous": "easy"}

_UPSERT_ACTIVITY = text(
    """
    INSERT INTO completed_activities (
        athlete_id, client_mutation_id, request_fingerprint, provider, provider_activity_id,
        duration_minutes, rpe, performed_at, timezone_snapshot, local_training_date, session_load,
        distance_km, device_metrics, structure
    ) VALUES (
        :athlete_id, :client_mutation_id, :request_fingerprint, 'garmin', :provider_activity_id,
        :duration_minutes, :rpe, :performed_at, :timezone_snapshot, :local_training_date, :session_load,
        :distance_km, CAST(:device_metrics AS jsonb), '[]'::jsonb
    )
    ON CONFLICT (athlete_id, client_mutation_id) DO UPDATE SET
        provider = 'garmin', provider_activity_id = EXCLUDED.provider_activity_id,
        timezone_snapshot = EXCLUDED.timezone_snapshot, local_training_date = EXCLUDED.local_training_date,
        distance_km = EXCLUDED.distance_km, device_metrics = EXCLUDED.device_metrics, deleted_at = NULL
    RETURNING id
    """
)

_UPSERT_TELEMETRY = text(
    """
    INSERT INTO activity_telemetry (
        activity_id, athlete_id, source, sport, sub_sport, device, hr_profile, laps, timer_events,
        workout_steps, samples, hr_peak_30s, activity_name
    ) VALUES (
        :activity_id, :athlete_id, 'garmin_fit', :sport, :sub_sport, :device, CAST(:hr_profile AS jsonb),
        CAST(:laps AS jsonb), CAST(:timer_events AS jsonb), CAST(:workout_steps AS jsonb),
        CAST(:samples AS jsonb), :hr_peak_30s, :activity_name
    )
    ON CONFLICT (activity_id) DO UPDATE SET
        sport = EXCLUDED.sport, sub_sport = EXCLUDED.sub_sport, device = EXCLUDED.device,
        hr_profile = EXCLUDED.hr_profile, laps = EXCLUDED.laps, timer_events = EXCLUDED.timer_events,
        workout_steps = EXCLUDED.workout_steps, samples = EXCLUDED.samples, hr_peak_30s = EXCLUDED.hr_peak_30s,
        activity_name = EXCLUDED.activity_name
    """
)


def _load_runs(archive: zipfile.ZipFile) -> list[dict]:
    names = [n for n in archive.namelist() if n.endswith("_1_summarizedActivities.json")]
    if not names:
        raise RuntimeError("No *_1_summarizedActivities.json in the export")
    with archive.open(names[0]) as f:
        acts = json.load(f)[0]["summarizedActivitiesExport"]
    return [a for a in acts if a.get("activityType") in _RUNNING_TYPES]


def _iter_fit_files(archive: zipfile.ZipFile):
    for name in archive.namelist():
        if "UploadedFiles" in name and name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive.read(name))) as inner:
                for fit_name in inner.namelist():
                    if fit_name.lower().endswith(".fit"):
                        yield fit_name, inner.read(fit_name)


def _device_metrics(a: dict) -> dict:
    """Same unit conventions as backfill_garmin_metrics.py (distances and
    elevations in cm, calories actually kJ, avgDoubleCadence = steps/min)."""
    m: dict = {}
    if a.get("avgHr") is not None:
        m["avgHeartRate"] = round(a["avgHr"])
    if a.get("maxHr") is not None:
        m["maxHeartRate"] = round(a["maxHr"])
    if a.get("avgDoubleCadence") is not None:
        m["avgCadenceStepsPerMin"] = round(a["avgDoubleCadence"])
    if a.get("maxDoubleCadence") is not None:
        m["maxCadenceStepsPerMin"] = round(a["maxDoubleCadence"])
    if a.get("avgStrideLength") is not None:
        m["avgStrideLengthM"] = round(a["avgStrideLength"] / 100, 1)
    if a.get("elevationGain") is not None:
        m["elevationGainM"] = round(a["elevationGain"] / 100, 1)
    if a.get("elevationLoss") is not None:
        m["elevationLossM"] = round(a["elevationLoss"] / 100, 1)
    if a.get("calories") is not None:
        m["calories"] = round(a["calories"] / 4.184)
    if a.get("aerobicTrainingEffect") is not None:
        m["aerobicTrainingEffect"] = round(a["aerobicTrainingEffect"], 1)
    if a.get("anaerobicTrainingEffect") is not None:
        m["anaerobicTrainingEffect"] = round(a["anaerobicTrainingEffect"], 1)
    if a.get("trainingEffectLabel"):
        m["trainingEffectLabel"] = a["trainingEffectLabel"]
    return m


def _moving_median_speed(tele: dict) -> float | None:
    g = build_grid(tele["samples"], tele["timer_events"])
    moving = sorted(v for v in g.v if v >= MOVING_SPEED)
    return moving[len(moving) // 2] if moving else None


def structure_from_detection(analysis: dict, detection: dict) -> list[dict]:
    """Detected segments -> the WorkoutAssignmentSegment shape History's
    workout-structure view already renders (reps of one block grouped)."""
    out: list[dict] = []
    stats = analysis["segments"]
    i = 0
    while i < len(stats):
        s = stats[i]
        role = s["role"]
        if role in ("warmup", "cooldown", "steady"):
            kind = {"warmup": "warmup", "cooldown": "cooldown", "steady": "jog"}[role]
            seg = {"kind": kind, "label": {"warmup": "熱身", "cooldown": "收操", "jog": "連續跑"}[kind],
                   "distanceMeters": round(s["gps_distance_m"]), "durationSeconds": s["elapsed_s"]}
            if fmt_pace(s["pace_s_per_km"]):
                seg["pace"] = fmt_pace(s["pace_s_per_km"]).replace("/km", " /km")
            out.append(seg)
            i += 1
            continue
        if role == "work":
            block = []
            rests = []
            while i < len(stats) and stats[i]["role"] in ("work", "rest"):
                if stats[i]["role"] == "work":
                    block.append(stats[i])
                else:
                    rests.append(stats[i]["elapsed_s"])
                i += 1
            dists = [round(r["distance_m"]) for r in block]
            total_t = sum(r["moving_s"] for r in block)
            total_d = sum(r["distance_m"] for r in block)
            seg = {"kind": "interval", "label": "間歇" if detection["kind"] == "intervals" else "節奏",
                   "repetitions": len(block), "distancesMeters": dists,
                   "pace": fmt_pace(total_t / (total_d / 1000)).replace("/km", " /km") if total_d else None,
                   "pacesPerRep": [(fmt_pace(r["pace_s_per_km"]) or "").replace("/km", " /km") or None for r in block]}
            if rests:
                seg["restSeconds"] = round(statistics.fmean(rests))
            out.append(seg)
            continue
        if role in ("set_rest", "rest", "strides"):
            out.append({"kind": "rest" if role != "strides" else "jog",
                        "label": {"set_rest": "組間休息", "rest": "休息", "strides": "加速跑"}[role],
                        "durationSeconds": s["elapsed_s"]})
        i += 1
    return out[:50]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--email", default="runner.tokyo@runsense.demo")
    parser.add_argument("--timezone", default="Asia/Taipei",
                        help="where the athlete actually ran (used for local training dates)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tz = ZoneInfo(args.timezone)
    with zipfile.ZipFile(args.zip_path) as archive:
        runs = _load_runs(archive)
        by_start = {int(a["beginTimestamp"]) // 1000: a for a in runs}
        teles: dict[int, dict] = {}
        bad_files = 0
        for _name, data in _iter_fit_files(archive):
            try:
                tele = parse_fit(data)
            except FitParseError:
                bad_files += 1
                continue
            key = int(tele["start_time"].timestamp())
            if tele["sport"] == "running" and key in by_start:
                teles[key] = tele
    print(f"{len(runs)} running activities in the export, {len(teles)} matched to a .fit file "
          f"({bad_files} non-activity / unreadable .fit files ignored).")

    # athlete's easy pace: median moving speed of the runs that are plainly
    # continuous (first pass, no baseline yet)
    easy_speeds = []
    for tele in teles.values():
        if detect_workout(tele)["kind"] == "continuous":
            s = _moving_median_speed(tele)
            if s:
                easy_speeds.append(s)
    easy_speed = statistics.median(easy_speeds) if easy_speeds else None
    if easy_speed:
        print(f"Easy-run baseline from {len(easy_speeds)} continuous runs: {fmt_pace(1000 / easy_speed)}")

    if args.dry_run:
        kinds: dict[str, int] = {}
        for tele in teles.values():
            k = detect_workout(tele, easy_speed)["kind"]
            kinds[k] = kinds.get(k, 0) + 1
        print("Detected:", kinds, "-- dry run, no database changes.")
        return

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            athlete_id = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": args.email}).scalar_one_or_none()
            if athlete_id is None:
                raise RuntimeError(f"No user {args.email} -- run seed_demo_personas.py first")
            lock_athlete_training_load(conn, athlete_id)

            removed = 0
            for prefix in _SYNTHETIC_PREFIXES:
                removed += conn.execute(
                    text("DELETE FROM completed_activities WHERE athlete_id = :a AND request_fingerprint LIKE :p "
                         "AND id NOT IN (SELECT activity_id FROM activity_telemetry)"),
                    {"a": athlete_id, "p": prefix},
                ).rowcount
            print(f"Removed {removed} synthetic activities for {args.email}.")

            imported = skipped_rpe = 0
            dates: list[date] = []
            kinds: dict[str, int] = {}
            for start_key, a in sorted(by_start.items()):
                rpe_raw = a.get("workoutRpe")
                if rpe_raw is None:
                    skipped_rpe += 1
                    continue
                rpe = max(1, min(10, round(rpe_raw / 10)))
                duration = Decimal(str((a.get("duration") or 0) / 1000 / 60))
                if duration <= 0:
                    continue
                performed_at = datetime.fromtimestamp(start_key, tz=timezone.utc)
                local_date = performed_at.astimezone(tz).date()
                cmid = uuid.uuid5(uuid.NAMESPACE_URL, f"garmin-import:{args.email}:{a['activityId']}")
                activity_id = conn.execute(_UPSERT_ACTIVITY, {
                    "athlete_id": athlete_id, "client_mutation_id": cmid,
                    "request_fingerprint": f"garmin-import:{cmid}", "provider_activity_id": str(a["activityId"]),
                    "duration_minutes": duration, "rpe": rpe, "performed_at": performed_at,
                    "timezone_snapshot": args.timezone, "local_training_date": local_date,
                    "session_load": duration * rpe,
                    "distance_km": round(a["distance"] / 100_000, 2) if a.get("distance") else None,
                    "device_metrics": json.dumps(_device_metrics(a)),
                }).scalar_one()
                dates.append(local_date)
                imported += 1

                tele = teles.get(start_key)
                if tele is None:
                    continue
                conn.execute(_UPSERT_TELEMETRY, {
                    "activity_id": activity_id, "athlete_id": athlete_id, "sport": tele["sport"],
                    "sub_sport": tele["sub_sport"], "device": tele["device"],
                    "hr_profile": json.dumps(tele["hr_profile"]), "laps": json.dumps(tele["laps"]),
                    "timer_events": json.dumps(tele["timer_events"]),
                    "workout_steps": json.dumps(tele["workout_steps"]),
                    "samples": json.dumps(tele["samples"]), "hr_peak_30s": peak_rolling_hr(tele["samples"]),
                    "activity_name": (a.get("name") or "").strip() or None,
                })
                detection = detect_workout(tele, easy_speed)
                kinds[detection["kind"]] = kinds.get(detection["kind"], 0) + 1
                auto_summary: dict = {"kind": detection["kind"], "signature": detection["signature"],
                                      "confidence": detection["confidence"],
                                      "moving_median_speed": _moving_median_speed(tele)}
                if detection["segments"]:
                    hr = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=tele["hr_profile"],
                                            history_peak_30s=None, birth_year=None, on_date=local_date)
                    analysis = analyse_workout(tele, detection["segments"],
                                               session_type=_KIND_TO_SESSION.get(detection["kind"], "other"),
                                               target_pace_s_per_km=None, hr=hr, easy_speed=easy_speed)
                    summ = analysis["summary"]
                    auto_summary.update({
                        "mean_pace_s_per_km": summ.get("mean_work_pace_s_per_km") or summ.get("split_mean_pace_s_per_km"),
                        "mean_rep_hr": summ.get("mean_rep_hr"),
                        "rep_count": summ.get("rep_count"),
                    })
                    conn.execute(
                        text("UPDATE completed_activities SET structure = CAST(:s AS jsonb) WHERE id = :id"),
                        {"s": json.dumps(structure_from_detection(analysis, detection)), "id": activity_id},
                    )
                conn.execute(
                    text("UPDATE activity_telemetry SET auto_detection = CAST(:d AS jsonb), "
                         "auto_summary = CAST(:s AS jsonb) WHERE activity_id = :id"),
                    {"d": json.dumps(detection), "s": json.dumps(auto_summary), "id": activity_id},
                )

            print(f"Imported {imported} activities ({skipped_rpe} skipped: no self-reported RPE). "
                  f"Detected structure: {kinds}")

            if dates:
                day = min(dates)
                today = datetime.now(timezone.utc).date()
                while day <= today:
                    recompute_training_load(conn, athlete_id, day)
                    day += timedelta(days=28)
    finally:
        engine.dispose()
    print("Done.")


if __name__ == "__main__":
    main()

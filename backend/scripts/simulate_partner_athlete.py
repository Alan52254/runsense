"""Simulate a training partner's history from a real athlete's: same coach,
same sessions, a slightly stronger runner. For the demo's second athlete,
who has no real watch data.

Run manually from backend/:

    python scripts/simulate_partner_athlete.py --source runner.tokyo@runsense.demo \\
        --target runner.london@runsense.demo --speedup 1.03

Every one of the source athlete's recorded runs (with per-second telemetry)
becomes a run for the target athlete on the same date at the same local
clock time in the target's timezone (+/- a few minutes):

- running is faster by `speedup` (+/- 1% per session): the time spent
  moving is compressed, distances stay -- a 400 m rep is still 400 m, it
  just takes less time; recoveries and stops keep their length;
- heart rate is a few beats lower, against the target's own max / resting
  heart rate and HR zones (same zone percentages as the source's watch);
- self-reported RPE is the source's.

Every simulated row is labelled: provider_activity_id "simulated-...",
request_fingerprint "simulated-partner:...", telemetry source "simulated"
-- the app shows them as 模擬資料 and nothing here can be mistaken for a
recording. The target's previous rows are replaced. The source's coach
assignments are copied too, with targets ~2.5% faster rounded the way a
coach writes them.
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import random
import re
import statistics
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.fit_telemetry import peak_rolling_hr  # noqa: E402
from app.training_load_store import lock_athlete_training_load, recompute_training_load  # noqa: E402
from app.workout_analysis import analyse_workout, resolve_hr_profile  # noqa: E402
from app.workout_prescription import coach_round, describe, from_assignment  # noqa: E402
from app.workout_segmentation import MOVING_SPEED, detect_workout  # noqa: E402
from import_garmin_fit_telemetry import _KIND_TO_SESSION, _moving_median_speed, structure_from_detection  # noqa: E402

_PARTNER_MAX_HR = 198
_PARTNER_RESTING_HR = 52
_HR_SHIFT = 3


def _warp(tele: dict, k: float, rng: random.Random) -> tuple[dict, Callable[[float], float]]:
    """Compress the time spent moving by k; returns the new telemetry and
    the old-time -> new-time mapping."""
    s = tele["samples"]
    t_old = s["t"]
    v_old = s["v"]
    new_t = [0.0]
    for i in range(1, len(t_old)):
        dt = t_old[i] - t_old[i - 1]
        v = v_old[i] if v_old[i] is not None else 0.0
        new_t.append(new_t[-1] + (dt / k if v >= MOVING_SPEED else dt))

    def remap(x: float) -> float:
        if not t_old:
            return x
        if x <= t_old[0]:
            return x
        if x >= t_old[-1]:
            return new_t[-1] + (x - t_old[-1])
        j = bisect.bisect_right(t_old, x) - 1
        span = t_old[j + 1] - t_old[j]
        frac = (x - t_old[j]) / span if span else 0
        return new_t[j] + frac * (new_t[j + 1] - new_t[j])

    out = {"t": [], "d": [], "v": [], "hr": [], "cad": []}
    last = None
    for i, t in enumerate(new_t):
        ti = round(t)
        if ti == last:
            continue
        last = ti
        v = s["v"][i]
        moving = v is not None and v >= MOVING_SPEED
        hr = s["hr"][i]
        cad = s["cad"][i]
        out["t"].append(ti)
        out["d"].append(s["d"][i])
        out["v"].append(round(v * k, 3) if moving else v)
        out["hr"].append(max(45, hr - _HR_SHIFT - (1 if rng.random() < 0.3 else 0)) if hr else hr)
        out["cad"].append(cad + 1 if cad and moving else cad)

    laps = []
    for lap in tele["laps"]:
        start = lap.get("start_offset_s")
        if start is None:
            laps.append(dict(lap))
            continue
        el = lap.get("elapsed_s") or 0
        new_start = remap(start)
        new_el = remap(start + el) - new_start
        ratio = new_el / el if el else 1
        laps.append({**lap, "start_offset_s": round(new_start, 1), "elapsed_s": round(new_el, 3),
                     "timer_s": round((lap.get("timer_s") or 0) * ratio, 3) if lap.get("timer_s") else lap.get("timer_s"),
                     "avg_hr": lap["avg_hr"] - _HR_SHIFT if lap.get("avg_hr") else lap.get("avg_hr"),
                     "max_hr": lap["max_hr"] - _HR_SHIFT if lap.get("max_hr") else lap.get("max_hr")})
    events = [[round(remap(at), 1), kind] for at, kind in tele["timer_events"]]
    return {**tele, "samples": out, "laps": laps, "timer_events": events}, remap


def _partner_hr_profile(src: dict) -> dict:
    prof = {"max_hr": _PARTNER_MAX_HR, "resting_hr": _PARTNER_RESTING_HR,
            "hr_calc_type": src.get("hr_calc_type") or "percent_hrr"}
    tops = src.get("zone_high_bounds")
    if tops and src.get("max_hr") and src.get("resting_hr"):
        fr = [(x - src["resting_hr"]) / (src["max_hr"] - src["resting_hr"]) for x in tops]
        prof["zone_high_bounds"] = [round(_PARTNER_RESTING_HR + f * (_PARTNER_MAX_HR - _PARTNER_RESTING_HR)) for f in fr]
    return prof


def _faster_pace_text(pace_text: str, distance: float | None, factor: float) -> str:
    m = re.search(r"(\d{1,2}):(\d{2}(?:\.\d+)?)", pace_text or "")
    if not m:
        return pace_text
    sec = (int(m.group(1)) * 60 + float(m.group(2))) / factor
    if distance and distance <= 600:
        lap = coach_round(sec * distance / 1000, lap=True)
        sec = lap / distance * 1000
    else:
        sec = coach_round(sec, lap=False)
    mm, ss = divmod(sec, 60)
    return f"{int(mm)}:{ss:04.1f} /km" if ss != int(ss) else f"{int(mm)}:{int(ss):02d} /km"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="runner.tokyo@runsense.demo")
    parser.add_argument("--target", default="runner.london@runsense.demo")
    parser.add_argument("--speedup", type=float, default=1.03)
    parser.add_argument("--assignment-speedup", type=float, default=1.025)
    args = parser.parse_args()

    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    try:
        with engine.begin() as conn:
            src_id = conn.execute(text("SELECT id FROM users WHERE email=:e"), {"e": args.source}).scalar_one()
            dst_id = conn.execute(text("SELECT id FROM users WHERE email=:e"), {"e": args.target}).scalar_one()
            dst_tz_name = conn.execute(text("SELECT timezone FROM athlete_profiles WHERE user_id=:u"),
                                       {"u": dst_id}).scalar_one()
            dst_tz = ZoneInfo(dst_tz_name)
            rows = conn.execute(text(
                """SELECT a.*, t.sport, t.sub_sport, t.device, t.hr_profile, t.laps, t.timer_events, t.workout_steps,
                          t.samples
                     FROM completed_activities a JOIN activity_telemetry t ON t.activity_id = a.id
                    WHERE a.athlete_id = :s AND a.deleted_at IS NULL ORDER BY a.performed_at"""),
                {"s": src_id}).mappings().all()
            print(f"{len(rows)} source runs with telemetry")

            lock_athlete_training_load(conn, dst_id)
            old = conn.execute(text("SELECT id FROM completed_activities WHERE athlete_id=:d"), {"d": dst_id}).scalars().all()
            for table in ("workout_analyses", "workout_prescriptions", "activity_telemetry"):
                conn.execute(text(f"DELETE FROM {table} WHERE athlete_id=:d"), {"d": dst_id})
            conn.execute(text("DELETE FROM completed_activities WHERE athlete_id=:d"), {"d": dst_id})
            print(f"Removed {len(old)} previous rows for {args.target}")

            speeds = []
            made = []
            for r in rows:
                rng = random.Random(str(r["id"]))
                k = args.speedup * (1 + rng.uniform(-0.01, 0.01))
                src_tele = {"sub_sport": r["sub_sport"], "laps": r["laps"], "timer_events": r["timer_events"],
                            "samples": r["samples"], "workout_steps": r["workout_steps"], "hr_profile": r["hr_profile"]}
                tele, remap = _warp(src_tele, k, rng)
                tele["hr_profile"] = _partner_hr_profile(r["hr_profile"] or {})
                src_tz = ZoneInfo(r["timezone_snapshot"] or "Asia/Taipei")
                local = r["performed_at"].astimezone(src_tz).replace(tzinfo=None) + timedelta(minutes=rng.randint(-15, 15))
                performed_at = local.replace(tzinfo=dst_tz).astimezone(timezone.utc)
                duration_s = float(r["duration_minutes"]) * 60
                new_duration = Decimal(str(round(remap(duration_s) / 60, 4)))
                metrics = dict(r["device_metrics"] or {})
                for key in ("avgHeartRate", "maxHeartRate"):
                    if metrics.get(key):
                        metrics[key] = metrics[key] - _HR_SHIFT
                if metrics.get("avgCadenceStepsPerMin"):
                    metrics["avgCadenceStepsPerMin"] += 1
                if metrics.get("calories"):
                    metrics["calories"] = round(metrics["calories"] * 0.95)
                cmid = uuid.uuid5(uuid.NAMESPACE_URL, f"simulated-partner:{args.target}:{r['id']}")
                new_id = conn.execute(text(
                    """INSERT INTO completed_activities (athlete_id, client_mutation_id, request_fingerprint, provider,
                         provider_activity_id, duration_minutes, rpe, performed_at, timezone_snapshot, local_training_date,
                         session_load, distance_km, device_metrics, structure)
                       VALUES (:a, :c, :f, 'garmin', :p, :dur, :rpe, :at, :tz, :ld, :load, :km, CAST(:m AS jsonb), '[]'::jsonb)
                       RETURNING id"""),
                    {"a": dst_id, "c": cmid, "f": f"simulated-partner:{cmid}", "p": f"simulated-{r['provider_activity_id']}",
                     "dur": new_duration, "rpe": r["rpe"], "at": performed_at, "tz": dst_tz_name,
                     "ld": local.date(), "load": new_duration * r["rpe"], "km": r["distance_km"],
                     "m": json.dumps(metrics)}).scalar_one()
                conn.execute(text(
                    """INSERT INTO activity_telemetry (activity_id, athlete_id, source, sport, sub_sport, device, hr_profile,
                         laps, timer_events, workout_steps, samples, hr_peak_30s)
                       VALUES (:id, :a, 'simulated', :sp, :ss, :dev, CAST(:hp AS jsonb), CAST(:l AS jsonb),
                               CAST(:te AS jsonb), CAST(:ws AS jsonb), CAST(:s AS jsonb), :peak)"""),
                    {"id": new_id, "a": dst_id, "sp": r["sport"], "ss": r["sub_sport"], "dev": r["device"],
                     "hp": json.dumps(tele["hr_profile"]), "l": json.dumps(tele["laps"]),
                     "te": json.dumps(tele["timer_events"]), "ws": json.dumps(tele["workout_steps"] or []),
                     "s": json.dumps(tele["samples"]), "peak": peak_rolling_hr(tele["samples"])})
                made.append((new_id, tele, local.date()))

            # easy pace of the simulated athlete, then detection as on import
            for new_id, tele, _d in made:
                if detect_workout(tele)["kind"] == "continuous":
                    s = _moving_median_speed(tele)
                    if s:
                        speeds.append(s)
            easy = statistics.median(speeds) if speeds else None
            kinds: dict[str, int] = {}
            for new_id, tele, on in made:
                detection = detect_workout(tele, easy)
                kinds[detection["kind"]] = kinds.get(detection["kind"], 0) + 1
                summary = {"kind": detection["kind"], "signature": detection["signature"],
                           "confidence": detection["confidence"], "moving_median_speed": _moving_median_speed(tele)}
                if detection["segments"]:
                    hr = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=tele["hr_profile"],
                                            history_peak_30s=None, birth_year=None, on_date=on)
                    analysis = analyse_workout(tele, detection["segments"],
                                               session_type=_KIND_TO_SESSION.get(detection["kind"], "other"),
                                               target_pace_s_per_km=None, hr=hr, easy_speed=easy)
                    summ = analysis["summary"]
                    summary.update({"mean_pace_s_per_km": summ.get("mean_work_pace_s_per_km")
                                    or summ.get("split_mean_pace_s_per_km"),
                                    "mean_rep_hr": summ.get("mean_rep_hr"), "rep_count": summ.get("rep_count")})
                    conn.execute(text("UPDATE completed_activities SET structure = CAST(:s AS jsonb) WHERE id = :id"),
                                 {"s": json.dumps(structure_from_detection(analysis, detection)), "id": new_id})
                conn.execute(text("UPDATE activity_telemetry SET auto_detection = CAST(:d AS jsonb), "
                                  "auto_summary = CAST(:s AS jsonb) WHERE activity_id = :id"),
                             {"d": json.dumps(detection), "s": json.dumps(summary), "id": new_id})
            print(f"Simulated {len(made)} runs: {kinds}")

            # the same coach's assignments, a little faster
            assigns = conn.execute(text(
                "SELECT team_id, local_date, title, duration_minutes, intensity_label, structure FROM assigned_workouts "
                "WHERE athlete_id = :s AND local_date >= '2026-09-01'"), {"s": src_id}).mappings().all()
            for a in assigns:
                structure = json.loads(json.dumps(a["structure"]))
                for seg in structure:
                    if seg.get("kind") != "interval":
                        continue
                    dist = seg.get("distanceMeters") or (seg.get("distancesMeters") or [None])[0]
                    if seg.get("pace"):
                        seg["pace"] = _faster_pace_text(seg["pace"], dist, args.assignment_speedup)
                    if seg.get("pacesPerRep"):
                        seg["pacesPerRep"] = [_faster_pace_text(p, d, args.assignment_speedup)
                                              for p, d in zip(seg["pacesPerRep"], seg.get("distancesMeters") or [])]
                presc = from_assignment(structure, a["title"])
                title = describe(presc) if presc else a["title"]
                ran = conn.execute(text("SELECT count(*) FROM completed_activities WHERE athlete_id=:d "
                                        "AND local_training_date=:ld"), {"d": dst_id, "ld": a["local_date"]}).scalar_one()
                conn.execute(text("DELETE FROM assigned_workouts WHERE athlete_id=:d AND local_date=:ld"),
                             {"d": dst_id, "ld": a["local_date"]})
                conn.execute(text(
                    """INSERT INTO assigned_workouts (team_id, athlete_id, local_date, title, duration_minutes,
                         intensity_label, status, structure)
                       VALUES (:t, :d, :ld, :title, :m, :l, :st, CAST(:s AS json))"""),
                    {"t": a["team_id"], "d": dst_id, "ld": a["local_date"], "title": title, "m": a["duration_minutes"],
                     "l": a["intensity_label"], "st": "COMPLETED" if ran else "MISSED",
                     "s": json.dumps(structure, ensure_ascii=False)})
                print(f"  assignment {a['local_date']}: {title}")

            dates = sorted({d for _i, _t, d in made})
            if dates:
                day = dates[0]
                today = datetime.now(timezone.utc).date()
                while day <= today:
                    recompute_training_load(conn, dst_id, day)
                    day += timedelta(days=28)
    finally:
        engine.dispose()
    print("Done.")


if __name__ == "__main__":
    main()

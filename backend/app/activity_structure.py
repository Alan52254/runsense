"""What a recorded run looked like, for History and for the same-workout
history: the activity's `structure` read off the detected segments, and its
easy-running speed. Shared by the Garmin export importer
(scripts/import_garmin_fit_telemetry.py) and the in-app .fit upload
(app/activity_upload.py)."""

from __future__ import annotations

import statistics

from app.workout_analysis import fmt_pace
from app.workout_segmentation import MOVING_SPEED, build_grid


def moving_median_speed(tele: dict) -> float | None:
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

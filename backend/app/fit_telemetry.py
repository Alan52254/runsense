"""Garmin .fit activity file -> the compact telemetry RunSense stores.

Keeps exactly what the workout analysis needs and nothing else: 1 Hz
distance / speed / heart rate / cadence, the watch's own laps (with how
each lap was triggered -- the athlete's lap-button presses are the most
exact rep boundaries there are), timer pause / resume events, structured
workout steps, and the heart-rate settings the watch used that day (max /
resting HR, the HR-zone boundaries and zone method). GPS positions are
deliberately not stored -- the analysis never needs where the athlete ran.

Times are seconds from the session start. Cadence is converted from the
FIT per-foot "strides per minute" (+ fractional part) to steps per minute.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import fitdecode


class FitParseError(ValueError):
    pass


def _value(frame: fitdecode.FitDataMessage, name: str) -> Any:
    try:
        return frame.get_value(name, fallback=None)
    except Exception:  # noqa: BLE001 -- malformed field in a third-party file
        return None


def _offset(ts: datetime | None, t0: datetime) -> float | None:
    return round((ts - t0).total_seconds(), 1) if ts is not None else None


def parse_fit(data: bytes) -> dict[str, Any]:
    """Parse one FIT activity. Raises FitParseError when the file has no
    session or no per-second records (not an activity recording)."""
    session: dict[str, Any] | None = None
    laps: list[dict[str, Any]] = []
    records: list[tuple] = []
    timer_events: list[tuple[datetime, str]] = []
    workout_steps: list[dict[str, Any]] = []
    hr_profile: dict[str, Any] = {}
    device = None
    try:
        with fitdecode.FitReader(io.BytesIO(data), check_crc=fitdecode.CrcCheck.DISABLED) as reader:
            for frame in reader:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                name = frame.name
                if name == "record":
                    ts = _value(frame, "timestamp")
                    if ts is None:
                        continue
                    speed = _value(frame, "enhanced_speed")
                    if speed is None:
                        speed = _value(frame, "speed")
                    cadence = _value(frame, "cadence")
                    fractional = _value(frame, "fractional_cadence") or 0
                    records.append((
                        ts,
                        _value(frame, "distance"),
                        speed,
                        _value(frame, "heart_rate"),
                        (cadence + fractional) * 2 if cadence is not None else None,
                    ))
                elif name == "lap":
                    laps.append({
                        "start": _value(frame, "start_time"),
                        "elapsed_s": _value(frame, "total_elapsed_time"),
                        "timer_s": _value(frame, "total_timer_time"),
                        "distance_m": _value(frame, "total_distance"),
                        "avg_hr": _value(frame, "avg_heart_rate"),
                        "max_hr": _value(frame, "max_heart_rate"),
                        "avg_cadence": _value(frame, "avg_running_cadence") or _value(frame, "avg_cadence"),
                        "trigger": _value(frame, "lap_trigger"),
                        "intensity": _value(frame, "intensity"),
                        "wkt_step": _value(frame, "wkt_step_index"),
                    })
                elif name == "session" and session is None:
                    session = {
                        "start": _value(frame, "start_time"),
                        "sport": _value(frame, "sport"),
                        "sub_sport": _value(frame, "sub_sport"),
                        "elapsed_s": _value(frame, "total_elapsed_time"),
                        "timer_s": _value(frame, "total_timer_time"),
                        "distance_m": _value(frame, "total_distance"),
                        "avg_hr": _value(frame, "avg_heart_rate"),
                        "max_hr": _value(frame, "max_heart_rate"),
                        # the athlete's own post-run rating, Garmin 0-100 scale
                        "workout_rpe": _value(frame, "workout_rpe"),
                        "calories": _value(frame, "total_calories"),
                        "avg_cadence": _value(frame, "avg_running_cadence") or _value(frame, "avg_cadence"),
                        "max_cadence": _value(frame, "max_running_cadence") or _value(frame, "max_cadence"),
                        "ascent_m": _value(frame, "total_ascent"),
                        "descent_m": _value(frame, "total_descent"),
                        "aerobic_te": _value(frame, "total_training_effect"),
                        "anaerobic_te": _value(frame, "total_anaerobic_training_effect"),
                    }
                elif name == "zones_target":
                    hr_profile["max_hr"] = _value(frame, "max_heart_rate")
                    hr_profile["threshold_hr"] = _value(frame, "threshold_heart_rate")
                    hr_profile["hr_calc_type"] = _value(frame, "hr_calc_type")
                elif name == "user_profile":
                    hr_profile["resting_hr"] = _value(frame, "resting_heart_rate")
                elif name == "time_in_zone" and _value(frame, "reference_mesg") == "session":
                    bounds = _value(frame, "hr_zone_high_boundary")
                    if bounds:
                        hr_profile["zone_high_bounds"] = [b for b in bounds if b is not None]
                    for key in ("max_heart_rate", "resting_heart_rate", "hr_calc_type"):
                        val = _value(frame, key)
                        if val is not None:
                            hr_profile.setdefault(
                                {"max_heart_rate": "max_hr", "resting_heart_rate": "resting_hr"}.get(key, key), val
                            )
                elif name == "event" and _value(frame, "event") == "timer":
                    ts = _value(frame, "timestamp")
                    if ts is not None:
                        timer_events.append((ts, str(_value(frame, "event_type"))))
                elif name == "workout_step":
                    workout_steps.append({
                        f.name: f.value for f in frame.fields
                        if f.value is not None and not f.name.startswith("unknown")
                        and isinstance(f.value, (int, float, str))
                    })
                elif name == "file_id":
                    device = _value(frame, "garmin_product") or _value(frame, "product")
    except fitdecode.FitError as exc:
        raise FitParseError(f"not a readable FIT file: {exc}") from exc

    if session is None or session["start"] is None or not records:
        raise FitParseError("FIT file has no activity session / records")

    t0: datetime = session["start"]
    samples: dict[str, list] = {"t": [], "d": [], "v": [], "hr": [], "cad": []}
    last_t = None
    for ts, dist, speed, hr, cad in records:
        t = round((ts - t0).total_seconds())
        if t < 0 or t == last_t:
            continue
        last_t = t
        samples["t"].append(t)
        samples["d"].append(round(dist, 1) if dist is not None else None)
        samples["v"].append(round(speed, 3) if speed is not None else None)
        samples["hr"].append(int(hr) if hr is not None else None)
        samples["cad"].append(round(cad) if cad is not None else None)

    lap_out = []
    for lap in laps:
        lap_out.append({
            "start_offset_s": _offset(lap["start"], t0),
            "elapsed_s": lap["elapsed_s"],
            "timer_s": lap["timer_s"],
            "distance_m": lap["distance_m"],
            "avg_hr": lap["avg_hr"],
            "max_hr": lap["max_hr"],
            "avg_cadence": (lap["avg_cadence"] * 2) if lap["avg_cadence"] else None,
            "trigger": str(lap["trigger"]) if lap["trigger"] is not None else None,
            "intensity": str(lap["intensity"]) if lap["intensity"] is not None else None,
            "wkt_step": lap["wkt_step"],
        })

    for key in ("hr_calc_type",):
        if hr_profile.get(key) is not None:
            hr_profile[key] = str(hr_profile[key])

    return {
        "start_time": t0,
        "sport": str(session["sport"]) if session["sport"] is not None else None,
        "sub_sport": str(session["sub_sport"]) if session["sub_sport"] is not None else None,
        "device": str(device) if device else None,
        "session": {k: v for k, v in session.items() if k not in ("start", "sport", "sub_sport")},
        "hr_profile": {k: v for k, v in hr_profile.items() if v is not None},
        "laps": lap_out,
        "timer_events": [[_offset(ts, t0), kind] for ts, kind in sorted(timer_events)],
        "workout_steps": workout_steps,
        "samples": samples,
    }


def peak_rolling_hr(samples: dict[str, list], window_s: int = 30) -> int | None:
    """Highest `window_s`-second rolling mean heart rate -- a far more
    trustworthy "max effort" reading than the single highest beat, which
    on a wrist sensor is often a cadence-lock spike."""
    pts = [(t, h) for t, h in zip(samples["t"], samples["hr"]) if h]
    if len(pts) < window_s // 2:
        return None
    best = None
    j = 0
    total = 0
    for i, (t, h) in enumerate(pts):
        total += h
        while pts[j][0] <= t - window_s:
            total -= pts[j][1]
            j += 1
        count = i - j + 1
        if count >= window_s * 0.6:
            mean = total / count
            if best is None or mean > best:
                best = mean
    return round(best) if best is not None else None

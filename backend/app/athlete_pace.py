"""A pace range for a suggested run, worked out from the Athlete's own runs.

Rules, not a model (ADR 0002): the Athlete's easy pace is the median pace of
their own easy-effort runs (session RPE <= 4, at least 2 km) over the last
180 days -- at least 5 of them, or there is no pace rather than a guess. Each
workout type sits in a fixed band around it (RunSense pace bands v1), and a
hot day slows the band by the reviewed weather model's speed loss. A cooler
than usual day never speeds it up: the band only ever errs slow.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import date, timedelta

from sqlalchemy import Connection, text

WINDOW_DAYS = 180
MIN_RUNS = 5
EASY_RPE_MAX = 4
MIN_KM = 2.0

# seconds per km relative to the easy pace: (fastest, slowest)
PACE_BANDS_V1: dict[str, tuple[int, int]] = {
    "RECOVERY_RUN": (20, 45),
    "EASY_RUN": (0, 20),
    "STEADY_RUN": (-20, -5),
}

_EASY_RUNS = text(
    """SELECT duration_minutes, distance_km FROM completed_activities
        WHERE athlete_id = :a AND deleted_at IS NULL AND rpe <= :rpe AND distance_km >= :km
          AND local_training_date BETWEEN :lo AND :hi""")


def easy_pace(tx: Connection, athlete_id: uuid.UUID, on: date) -> dict[str, int] | None:
    """{"s_per_km", "runs", "days"}: the median easy pace and what it rests on."""
    rows = tx.execute(_EASY_RUNS, {"a": athlete_id, "rpe": EASY_RPE_MAX, "km": MIN_KM,
                                   "lo": on - timedelta(days=WINDOW_DAYS), "hi": on}).all()
    paces = [float(r.duration_minutes) * 60 / float(r.distance_km) for r in rows]
    if len(paces) < MIN_RUNS:
        return None
    return {"s_per_km": round(statistics.median(paces)), "runs": len(paces), "days": WINDOW_DAYS}


def pace_range(workout_type: str, easy_s_per_km: int | None,
               speed_loss_pct: float | None = None) -> list[int] | None:
    """[fastest, slowest] seconds per km, rounded to 5 s; None for a type
    without a band (rest) or when there is no easy pace to anchor it."""
    band = PACE_BANDS_V1.get(workout_type)
    if band is None or easy_s_per_km is None:
        return None
    slow_down = 1 + max(0.0, speed_loss_pct or 0.0) / 100
    return [round((easy_s_per_km + offset) * slow_down / 5) * 5 for offset in band]


def pace_text(range_s_per_km: list[int] | None) -> str | None:
    """'6:00–6:20/km'"""
    if not range_s_per_km:
        return None
    lo, hi = (f"{s // 60}:{s % 60:02d}" for s in range_s_per_km)
    return f"{lo}–{hi}/km"

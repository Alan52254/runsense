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


# Reviewed per-workout-type ranges (s/km) used when the Athlete has too few
# easy runs to anchor the bands: the rule, not a guess about this Athlete.
RULE_DEFAULT_RANGES_V1: dict[str, list[int]] = {
    "RECOVERY_RUN": [380, 400],
    "EASY_RUN": [360, 380],
    "STEADY_RUN": [320, 340],
}

# A candidate's warm-up and cool-down (seconds), the rest of its time and
# distance being the main effort. Segment labels match the guidance engine's.
_SEGMENT_PLAN_V1: dict[str, tuple[int, int, str]] = {
    "RECOVERY_RUN": (300, 300, "超低強度主動恢復跑"),
    "EASY_RUN": (300, 300, "有氧基礎巡航跑"),
    "STEADY_RUN": (600, 300, "穩定巡航配速跑"),
}


def candidate_pace(workout_type: str, duration_minutes: int, distance_km: float,
                   easy_s_per_km: int | None) -> dict | None:
    """Target pace and warm-up / main / cool-down segments for one ranked
    candidate; None for a type that is not run (rest).

    The main effort sits in the workout type's band around the Athlete's easy
    pace (pace_source "athlete_history"), or in the reviewed default range when
    there is no easy pace ("rule_default"); warm-up and cool-down sit in the
    recovery band / range. The weather is not
    applied here -- the client adjusts the pace for conditions, once.
    """
    shape = _SEGMENT_PLAN_V1.get(workout_type)
    if shape is None:
        return None
    warmup_s, cooldown_s, main_label = shape
    if easy_s_per_km is not None:
        source = "athlete_history"
        main = pace_range(workout_type, easy_s_per_km)
        easy_jog = pace_range("RECOVERY_RUN", easy_s_per_km)
    else:
        source = "rule_default"
        main = list(RULE_DEFAULT_RANGES_V1[workout_type])
        easy_jog = list(RULE_DEFAULT_RANGES_V1["RECOVERY_RUN"])
    main_s = max(0, duration_minutes * 60 - warmup_s - cooldown_s)
    # warm-up and cool-down are counted at about 1 km together per 10 min
    main_m = max(0, round(distance_km * 1000) - round((warmup_s + cooldown_s) / 600) * 1000)

    def seg(id_: str, kind: str, label: str, seconds: int, rng: list[int],
            meters: int | None = None) -> dict:
        return {"id": id_, "kind": kind, "label": label, "duration_seconds": seconds,
                "distance_meters": meters, "target_pace_sec_per_km": None,
                "target_pace_range_sec_per_km": rng}

    return {
        "pace_source": source,
        "target_pace_s_per_km": round(sum(main) / 2),
        "target_pace_range_s_per_km": main,
        "segments": [
            seg("warmup", "warmup", "熱身慢跑", warmup_s, easy_jog),
            seg("main", "work", main_label, main_s, main, main_m),
            seg("cooldown", "cooldown", "緩和慢跑", cooldown_s, easy_jog),
        ],
    }

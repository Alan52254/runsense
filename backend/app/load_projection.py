"""What a plan would do to an athlete's load ratio, shown before it is scheduled.

The same ratio as app/training_load.py -- the last 7 days' session load over
a quarter of the last 28 days' -- computed on the plan's last day with the
planned sessions added. A planned session's load is its minutes times an RPE
estimated from its session type (RunSense planned RPE v1), since nobody has
run it yet; the card says so. Only numbers are given, never a risk colour
(no alert threshold has been reviewed, SRS REQ-ALERT-001).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Mapping

from sqlalchemy import Connection, text

BASIS = "planned_rpe_by_session_type"
# session type (assignment intensity label) -> the RPE a session of it is
# expected to be felt at
PLANNED_RPE_V1: dict[str, int] = {
    "恢復跑": 2, "輕鬆跑": 3, "長距離": 4, "穩定跑": 5, "跑步": 5, "節奏跑": 6, "間歇": 7, "比賽": 9,
}

# the materialized daily load: what a coach may read under the athlete's
# training_load consent (activities themselves need activity_summary)
_DAILY_LOAD = text(
    """SELECT date AS d, session_load AS load FROM training_load_daily
        WHERE athlete_id = :a AND unit = 'AU' AND date BETWEEN :lo AND :hi""")


def planned_load(minutes: float, intensity_label: str) -> float:
    return float(minutes) * PLANNED_RPE_V1.get(intensity_label, PLANNED_RPE_V1["跑步"])


def ratio_on(day: date, loads: Mapping[date, float]) -> float | None:
    acute = sum(v for d, v in loads.items() if day - timedelta(days=6) <= d <= day)
    chronic = sum(v for d, v in loads.items() if day - timedelta(days=27) <= d <= day) / 4
    return round(acute / chronic, 2) if chronic > 0 else None


def project(tx: Connection, athlete_id: uuid.UUID, today: date,
            planned: Mapping[date, float]) -> dict[str, object] | None:
    """{"before": today's ratio, "after": the ratio on the plan's last day
    with it scheduled, "on", "basis"}; None when the plan has no day from
    today on, or there is no load history to divide by."""
    ahead = {d: v for d, v in planned.items() if d >= today}
    if not ahead:
        return None
    last = max(ahead)
    actual = {r.d: float(r.load) for r in tx.execute(
        _DAILY_LOAD, {"a": athlete_id, "lo": today - timedelta(days=27), "hi": today}).all()}
    with_plan = dict(actual)
    for d, v in ahead.items():
        with_plan[d] = with_plan.get(d, 0.0) + v
    before, after = ratio_on(today, actual), ratio_on(last, with_plan)
    if before is None or after is None:
        return None
    return {"before": before, "after": after, "on": last.isoformat(), "basis": BASIS}

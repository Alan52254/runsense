"""Climate-equivalent pace adjustment. See design.md Decision 3: this is an
explicit, isolated, swappable heuristic -- neither SRS document specifies a
formula, so this one is not a scientific claim, just a documented default.
"""

from __future__ import annotations

_BASELINE_C = 15.0
_SEC_PER_KM_PER_DEGREE = 3.0
_HUMIDITY_THRESHOLD_PCT = 50.0
_MAX_ADJUSTMENT_SEC_PER_KM = 60


def pace_adjustment_sec_per_km(temperature_c: float, humidity_pct: float) -> int:
    degrees_over_baseline = max(0.0, temperature_c - _BASELINE_C)
    humidity_multiplier = 1 + max(0.0, humidity_pct - _HUMIDITY_THRESHOLD_PCT) / 100
    raw = degrees_over_baseline * _SEC_PER_KM_PER_DEGREE * humidity_multiplier
    return min(round(raw), _MAX_ADJUSTMENT_SEC_PER_KM)

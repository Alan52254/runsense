"""Deterministic per-unit Training Load Trend calculation.

The module deliberately exposes one calculation interface. Window expansion,
observation semantics, quality precedence, Decimal normalization, and canonical
snapshot hashing stay private so every mutation path uses identical rules.

TRAINING_LOAD_ALGORITHM_VERSION changes only when the declared calculation
semantics change; implementation-only refactors retain ``tl-v1``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

TRAINING_LOAD_ALGORITHM_VERSION = "tl-v1"
TRAINING_LOAD_SCHEMA_VERSION = 1
_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class DailyLoadInput:
    activity_id: str
    local_training_date: date
    performed_at: datetime
    session_load: Decimal
    unit: str
    source_metric: str


@dataclass(frozen=True, slots=True)
class DailyTrainingLoad:
    date: date
    unit: str
    session_load: Decimal
    source_metric: str
    acute_load: Decimal
    chronic_load: Decimal
    load_ratio: Decimal | None
    data_quality: str
    observation_days: int
    algorithm_version: str
    schema_version: int
    input_snapshot_hash: str


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("performed_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _snapshot_hash(
    *,
    point_date: date,
    unit: str,
    inputs: Sequence[DailyLoadInput],
    rest_dates: set[date],
) -> str:
    window_start = point_date - timedelta(days=27)
    # Every activity in the window is canonical input for every unit point:
    # unlike-unit presence controls LOW quality even though load arithmetic
    # remains unit-specific. Therefore a Garmin input must also change the AU
    # snapshot hash when it changes AU's quality.
    relevant = sorted(
        (
            item
            for item in inputs
            if window_start <= item.local_training_date <= point_date
        ),
        key=lambda item: (
            item.local_training_date,
            _utc_iso(item.performed_at),
            item.activity_id,
        ),
    )
    snapshot = {
        "activities": [
            {
                "activity_id": item.activity_id,
                "local_training_date": item.local_training_date.isoformat(),
                "performed_at": _utc_iso(item.performed_at),
                "session_load": format(_money(item.session_load), ".2f"),
                "source_metric": item.source_metric,
                "unit": item.unit,
            }
            for item in relevant
        ],
        "confirmed_rest_dates": sorted(
            day.isoformat() for day in rest_dates if window_start <= day <= point_date
        ),
        "date": point_date.isoformat(),
        "schema_version": TRAINING_LOAD_SCHEMA_VERSION,
        "unit": unit,
    }
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_training_load_series(
    *,
    daily_inputs: Sequence[DailyLoadInput],
    confirmed_rest_dates: set[date],
    end_date: date,
    units: set[str],
) -> list[DailyTrainingLoad]:
    """Return 28 ascending daily points for every requested unit (and AU).

    Windows are inclusive: acute covers point-6 through point and chronic
    covers point-27 through point. Missing dates never become observations.
    """

    reported_units = set(units)
    reported_units.add("AU")
    inputs = tuple(daily_inputs)
    output: list[DailyTrainingLoad] = []

    unit_source_metrics: dict[str, str] = {
        "AU": "SESSION_RPE",
        "garmin_epoc": "GARMIN_EPOC",
    }
    for item in sorted(inputs, key=lambda value: (value.unit, value.source_metric)):
        unit_source_metrics.setdefault(item.unit, item.source_metric)

    ordered_units = sorted(reported_units, key=lambda value: (value != "AU", value))
    for unit in ordered_units:
        source_metric = unit_source_metrics.get(unit, unit.upper())
        for offset in range(27, -1, -1):
            point_date = end_date - timedelta(days=offset)
            chronic_start = point_date - timedelta(days=27)
            acute_start = point_date - timedelta(days=6)
            window_inputs = [
                item
                for item in inputs
                if chronic_start <= item.local_training_date <= point_date
            ]
            unit_inputs = [item for item in window_inputs if item.unit == unit]
            daily_load = _money(
                sum(
                    (
                        item.session_load
                        for item in unit_inputs
                        if item.local_training_date == point_date
                    ),
                    Decimal(0),
                )
            )
            acute_load = _money(
                sum(
                    (
                        item.session_load
                        for item in unit_inputs
                        if acute_start <= item.local_training_date <= point_date
                    ),
                    Decimal(0),
                )
            )
            chronic_total = sum(
                (item.session_load for item in unit_inputs), Decimal(0)
            )
            chronic_load = _money(chronic_total / Decimal(4))
            activity_dates = {item.local_training_date for item in unit_inputs}
            rest_in_window = {
                day for day in confirmed_rest_dates if chronic_start <= day <= point_date
            }
            observation_days = len(activity_dates | rest_in_window)
            mixed_units = len({item.unit for item in window_inputs}) > 1

            if observation_days < 21 or chronic_load == _ZERO:
                quality = "INSUFFICIENT"
                ratio = None
            else:
                quality = "LOW" if mixed_units else "SUFFICIENT"
                ratio = _money(acute_load / chronic_load)

            output.append(
                DailyTrainingLoad(
                    date=point_date,
                    unit=unit,
                    session_load=daily_load,
                    source_metric=source_metric,
                    acute_load=acute_load,
                    chronic_load=chronic_load,
                    load_ratio=ratio,
                    data_quality=quality,
                    observation_days=observation_days,
                    algorithm_version=TRAINING_LOAD_ALGORITHM_VERSION,
                    schema_version=TRAINING_LOAD_SCHEMA_VERSION,
                    input_snapshot_hash=_snapshot_hash(
                        point_date=point_date,
                        unit=unit,
                        inputs=inputs,
                        rest_dates=confirmed_rest_dates,
                    ),
                )
            )
    return output

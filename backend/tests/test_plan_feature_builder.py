"""plan_feature_builder: real activity history -> de-identified FeatureRows."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from app.plan_feature_builder import build_history_feature_rows, observed_intensity
from ml.feature_contract import validate_row


def test_observed_intensity_buckets_by_duration_and_rpe():
    assert observed_intensity(None, None) == 0
    assert observed_intensity(25, 4) == 1        # short -> recovery
    assert observed_intensity(40, 5) == 2        # mid -> easy
    assert observed_intensity(70, 5) == 3        # long -> steady
    assert observed_intensity(40, 7) == 3        # high rpe -> steady


class _Result:
    def __init__(self, rows=None, first=None):
        self._rows = rows or []
        self._first = first

    def fetchall(self):
        return self._rows

    def first(self):
        return self._first


class _Tx:
    """Serves the four queries build_history_feature_rows issues, in order:
    activities, training_load_daily, injury_reports, weather_cache."""

    def __init__(self, activities, loads, injuries, weather):
        self._responses = [
            _Result(rows=activities),
            _Result(rows=loads),
            _Result(rows=injuries),
            _Result(first=weather),
        ]
        self.i = 0

    def execute(self, *_a, **_k):
        r = self._responses[self.i]
        self.i += 1
        return r


def test_builds_one_labelled_query_per_activity_day_with_valid_contract_rows():
    d0 = date(2026, 8, 20)
    # newest-first, as `ORDER BY local_training_date DESC` returns them
    activities = [
        SimpleNamespace(local_training_date=d0 + timedelta(days=4), duration_minutes=25, rpe=3),  # recovery -> 1
        SimpleNamespace(local_training_date=d0 + timedelta(days=2), duration_minutes=70, rpe=7),  # steady -> 3
        SimpleNamespace(local_training_date=d0, duration_minutes=40, rpe=5),          # easy -> 2
    ]
    loads = [
        SimpleNamespace(date=d0, acute_load=300.0, chronic_load=320.0, observation_days=25),
        SimpleNamespace(date=d0 + timedelta(days=4), acute_load=360.0, chronic_load=320.0, observation_days=27),
    ]
    injuries = [SimpleNamespace(local_training_date=d0 + timedelta(days=4), severity_band="MILD")]
    weather = SimpleNamespace(temperature_c=24.0, fetched_at=datetime.now(UTC))

    rows = build_history_feature_rows(_Tx(activities, loads, injuries, weather), uuid.uuid4())

    # 3 decisions x 4 candidates
    assert len(rows) == 12
    for r in rows:
        validate_row(r)  # de-identified + in-contract
        assert r.group == 0

    # exactly one positive per query, and it matches the observed intensity
    by_q: dict[int, list] = {}
    for r in rows:
        by_q.setdefault(r.query_id, []).append(r)
    labels_by_intensity = {
        q: next(int(x.features["candidate_intensity_ord"]) for x in cs if x.label == 1)
        for q, cs in by_q.items()
    }
    assert list(labels_by_intensity.values()) == [2, 3, 1]

    # the injured day carries the self-care triage feature
    injured_q = 2
    assert all(x.features["triage_self_care"] == 1.0 for x in by_q[injured_q])


def test_no_activity_history_yields_no_rows():
    weather = SimpleNamespace(temperature_c=None, fetched_at=None)
    assert build_history_feature_rows(_Tx([], [], [], weather), uuid.uuid4()) == []

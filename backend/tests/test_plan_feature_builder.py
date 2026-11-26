"""plan_feature_builder: real activity history -> de-identified FeatureRows."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
import uuid

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
    """SQL-dispatching fake transaction for plan_feature_builder tests."""

    def __init__(
        self,
        activities,
        loads,
        injuries,
        weather=None,
        *,
        profile=None,
        rest_days=None,
        hr_rows=None,
    ):
        self.activities = activities
        self.loads = loads
        self.injuries = injuries
        self.weather = weather
        self.profile = profile
        self.rest_days = rest_days or []
        self.hr_rows = hr_rows or []

    def execute(self, stmt, _params=None):
        sql = str(stmt)
        if "FROM completed_activities" in sql:
            return _Result(rows=self.activities)
        if "FROM training_load_daily" in sql:
            return _Result(rows=self.loads)
        if "FROM injury_reports" in sql:
            return _Result(rows=self.injuries)
        if "FROM athlete_profiles" in sql:
            return _Result(first=self.profile)
        if "FROM weather_cache" in sql:
            return _Result(first=self.weather)
        if "FROM athlete_rest_days" in sql:
            return _Result(rows=self.rest_days)
        if "FROM workout_analyses" in sql:
            return _Result(rows=self.hr_rows)
        return _Result()


def test_builds_one_labelled_query_per_activity_day_with_valid_contract_rows():
    d0 = date(2026, 8, 20)
    # newest-first, as `ORDER BY local_training_date DESC` returns them
    activities = [
        SimpleNamespace(local_training_date=d0 + timedelta(days=4), duration_minutes=25, distance_km=4.0, rpe=3),  # recovery -> 1
        SimpleNamespace(local_training_date=d0 + timedelta(days=2), duration_minutes=70, distance_km=12.0, rpe=7),  # steady -> 3
        SimpleNamespace(local_training_date=d0, duration_minutes=40, distance_km=7.0, rpe=5),          # easy -> 2
    ]
    loads = [
        SimpleNamespace(date=d0, acute_load=300.0, chronic_load=320.0, observation_days=25),
        SimpleNamespace(date=d0 + timedelta(days=4), acute_load=360.0, chronic_load=320.0, observation_days=27),
    ]
    injuries = [SimpleNamespace(local_training_date=d0 + timedelta(days=4), severity_band="MILD")]
    weather = SimpleNamespace(temperature_c=24.0, humidity_pct=65.0, fetched_at=datetime.now(UTC))

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


def test_decoupled_sex_rest_days_avg_hr_ramp_wellness_and_causality():
    today = datetime.now(UTC).date()
    d0 = today - timedelta(days=10)
    d_rest = today - timedelta(days=5)
    d_prev = today - timedelta(days=2)

    activities = [
        SimpleNamespace(local_training_date=today, duration_minutes=45, distance_km=8.0, rpe=5),
        SimpleNamespace(local_training_date=d_prev, duration_minutes=60, distance_km=10.0, rpe=6),
        SimpleNamespace(local_training_date=d0, duration_minutes=35, distance_km=6.0, rpe=4),
    ]
    loads = [
        SimpleNamespace(date=d0 - timedelta(days=1), acute_load=200.0, chronic_load=250.0, observation_days=20),
        SimpleNamespace(date=today - timedelta(days=7), acute_load=250.0, chronic_load=260.0, observation_days=23),
        SimpleNamespace(date=today - timedelta(days=1), acute_load=300.0, chronic_load=270.0, observation_days=28),
        # Same-day load on `today` should NOT leak into today's pre-decision features
        SimpleNamespace(date=today, acute_load=999.0, chronic_load=270.0, observation_days=29),
    ]
    profile = SimpleNamespace(sex="female", city="Taipei")
    weather = SimpleNamespace(temperature_c=32.0, humidity_pct=78.0, fetched_at=datetime.now(UTC))
    rest_days = [SimpleNamespace(date=d_rest)]
    hr_rows = [
        SimpleNamespace(local_training_date=d_prev, avg_hr=154.0),
        # Same-day HR on `today` should NOT leak into `today`
        SimpleNamespace(local_training_date=today, avg_hr=199.0),
    ]
    wellness = {today: (3.5, 6.2)}

    rows = build_history_feature_rows(
        _Tx(
            activities,
            loads,
            [],
            weather=weather,
            profile=profile,
            rest_days=rest_days,
            hr_rows=hr_rows,
        ),
        uuid.uuid4(),
        max_days=None,
        group=7,
        query_id_start=100,
        include_rest_days=True,
        wellness_by_date=wellness,
    )

    # 3 activity days + 1 rest day = 4 decisions -> 16 rows
    assert len(rows) == 16
    assert {r.group for r in rows} == {7}
    assert sorted({r.query_id for r in rows}) == [100, 101, 102, 103]

    by_q: dict[int, list] = {}
    for r in rows:
        validate_row(r)
        by_q.setdefault(r.query_id, []).append(r)

    # Rest day (qid=101) has label=1 on intensity 0
    rest_label = next(int(x.features["candidate_intensity_ord"]) for x in by_q[101] if x.label == 1)
    assert rest_label == 0

    # Today (qid=103) uses strictly < today load (300, not 999) and < today HR (154, not 199)
    today_feats = by_q[103][0].features
    assert today_feats["sex_female"] == 1.0
    assert today_feats["acute_load"] == 300.0
    assert today_feats["load_ramp_pct"] == 20.0  # (300 - 250) / 250 * 100
    assert today_feats["recent_avg_hr_bpm"] == 154.0
    assert today_feats["resting_hr_delta"] == 3.5
    assert today_feats["sleep_hours"] == 6.2
    assert today_feats["weather_actionable"] == 1.0
    assert "temp_vs_normal_c" in today_feats

    # Also test sex_female persists even when weather_cache is empty (None)
    rows_no_weather = build_history_feature_rows(
        _Tx(activities, loads, [], weather=None, profile=profile, rest_days=rest_days),
        uuid.uuid4(),
        include_rest_days=False,
    )
    assert len(rows_no_weather) == 12
    assert all(r.features["sex_female"] == 1.0 for r in rows_no_weather)

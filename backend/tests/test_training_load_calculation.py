from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.training_load import (
    TRAINING_LOAD_ALGORITHM_VERSION,
    TRAINING_LOAD_SCHEMA_VERSION,
    DailyLoadInput,
    calculate_training_load_series,
)


def _activity(
    day: date,
    load: str,
    *,
    activity_id: str | None = None,
    unit: str = "AU",
    source_metric: str = "SESSION_RPE",
) -> DailyLoadInput:
    return DailyLoadInput(
        activity_id=activity_id or f"activity-{day.isoformat()}-{load}-{unit}",
        local_training_date=day,
        performed_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
        session_load=Decimal(load),
        unit=unit,
        source_metric=source_metric,
    )


def _point(points, day: date, unit: str = "AU"):
    return next(point for point in points if point.date == day and point.unit == unit)


def test_worked_au_example_has_700_acute_500_chronic_and_1_4_ratio():
    end = date(2026, 8, 28)
    activities = [_activity(end - timedelta(days=27), "1300")]
    activities.extend(_activity(end - timedelta(days=i), "100") for i in range(7))
    rests = {end - timedelta(days=i) for i in range(7, 27)}

    result = calculate_training_load_series(
        daily_inputs=activities,
        confirmed_rest_dates=rests,
        end_date=end,
        units={"AU"},
    )

    point = _point(result, end)
    assert point.acute_load == Decimal("700.00")
    assert point.chronic_load == Decimal("500.00")
    assert point.load_ratio == Decimal("1.40")
    assert point.data_quality == "SUFFICIENT"


def test_same_date_aggregation_and_exact_window_boundaries():
    end = date(2026, 8, 28)
    activities = [
        _activity(end, "10", activity_id="a"),
        _activity(end, "20", activity_id="b"),
        _activity(end - timedelta(days=6), "70"),
        _activity(end - timedelta(days=7), "700"),
        _activity(end - timedelta(days=27), "2700"),
        _activity(end - timedelta(days=28), "28000"),
    ]
    rests = {end - timedelta(days=i) for i in range(28)}
    point = _point(
        calculate_training_load_series(
            daily_inputs=activities,
            confirmed_rest_dates=rests,
            end_date=end,
            units={"AU"},
        ),
        end,
    )
    assert point.session_load == Decimal("30.00")
    assert point.acute_load == Decimal("100.00")
    assert point.chronic_load == Decimal("875.00")
    assert point.observation_days == 28


def test_activity_rest_and_missing_dates_count_at_most_one_observation_each():
    end = date(2026, 8, 28)
    activity_day = end - timedelta(days=2)
    rest_day = end - timedelta(days=1)
    point = _point(
        calculate_training_load_series(
            daily_inputs=[_activity(activity_day, "10"), _activity(activity_day, "20")],
            confirmed_rest_dates={activity_day, rest_day},
            end_date=end,
            units={"AU"},
        ),
        end,
    )
    assert point.observation_days == 2


def test_insufficient_precedes_mixed_quality_and_suppresses_ratio():
    end = date(2026, 8, 28)
    rests = {end - timedelta(days=i) for i in range(1, 20)}
    inputs = [
        _activity(end, "100"),
        _activity(end, "50", unit="garmin_epoc", source_metric="GARMIN_EPOC"),
    ]
    points = calculate_training_load_series(
        daily_inputs=inputs,
        confirmed_rest_dates=rests,
        end_date=end,
        units={"AU", "garmin_epoc"},
    )
    for unit in ("AU", "garmin_epoc"):
        point = _point(points, end, unit)
        assert point.observation_days == 20
        assert point.data_quality == "INSUFFICIENT"
        assert point.load_ratio is None


def test_all_rest_is_insufficient_even_with_28_observations():
    end = date(2026, 8, 28)
    point = _point(
        calculate_training_load_series(
            daily_inputs=[],
            confirmed_rest_dates={end - timedelta(days=i) for i in range(28)},
            end_date=end,
            units={"AU"},
        ),
        end,
    )
    assert point.observation_days == 28
    assert point.chronic_load == Decimal("0.00")
    assert point.data_quality == "INSUFFICIENT"
    assert point.load_ratio is None


def test_sufficient_mixed_units_are_separate_and_low_quality():
    end = date(2026, 8, 28)
    rests = {end - timedelta(days=i) for i in range(28)}
    points = calculate_training_load_series(
        daily_inputs=[
            _activity(end, "300"),
            _activity(end, "300", unit="garmin_epoc", source_metric="GARMIN_EPOC"),
        ],
        confirmed_rest_dates=rests,
        end_date=end,
        units={"AU", "garmin_epoc"},
    )
    au = _point(points, end, "AU")
    epoc = _point(points, end, "garmin_epoc")
    assert au.session_load == Decimal("300.00")
    assert epoc.session_load == Decimal("300.00")
    assert au.data_quality == epoc.data_quality == "LOW"
    assert au.load_ratio is not None and epoc.load_ratio is not None


def test_hash_is_order_independent_but_changes_with_meaningful_input():
    end = date(2026, 8, 28)
    a = _activity(end, "10", activity_id="a")
    b = _activity(end - timedelta(days=1), "20", activity_id="b")

    def digest(inputs):
        return _point(
            calculate_training_load_series(
                daily_inputs=inputs,
                confirmed_rest_dates={end - timedelta(days=2)},
                end_date=end,
                units={"AU"},
            ),
            end,
        ).input_snapshot_hash

    assert digest([a, b]) == digest([b, a])
    assert digest([a, b]) != digest([a, _activity(b.local_training_date, "21", activity_id="b")])
    assert digest([a, b]) != digest(
        [
            a,
            b,
            _activity(
                end,
                "5",
                activity_id="garmin",
                unit="garmin_epoc",
                source_metric="GARMIN_EPOC",
            ),
        ]
    )


def test_returns_exactly_28_points_per_unit_with_stable_versions():
    end = date(2026, 8, 28)
    points = calculate_training_load_series(
        daily_inputs=[], confirmed_rest_dates=set(), end_date=end, units={"AU", "garmin_epoc"}
    )
    assert len(points) == 56
    for unit in ("AU", "garmin_epoc"):
        series = [point for point in points if point.unit == unit]
        assert [point.date for point in series] == [end - timedelta(days=i) for i in range(27, -1, -1)]
        assert {point.algorithm_version for point in series} == {TRAINING_LOAD_ALGORITHM_VERSION}
        assert {point.schema_version for point in series} == {TRAINING_LOAD_SCHEMA_VERSION}

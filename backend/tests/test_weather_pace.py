"""Pure unit tests -- no DB needed."""

from __future__ import annotations

from app.weather_pace import pace_adjustment_sec_per_km


def test_at_or_below_baseline_temperature_has_no_adjustment():
    assert pace_adjustment_sec_per_km(15.0, 40.0) == 0
    assert pace_adjustment_sec_per_km(5.0, 40.0) == 0


def test_above_baseline_scales_with_degrees_over():
    low = pace_adjustment_sec_per_km(20.0, 40.0)
    high = pace_adjustment_sec_per_km(30.0, 40.0)
    assert 0 < low < high


def test_high_humidity_increases_the_adjustment_at_the_same_temperature():
    dry = pace_adjustment_sec_per_km(28.0, 40.0)
    humid = pace_adjustment_sec_per_km(28.0, 90.0)
    assert humid > dry


def test_adjustment_is_capped():
    extreme = pace_adjustment_sec_per_km(45.0, 100.0)
    assert extreme <= 60

"""Pure unit tests -- no DB needed. Uses a representative Taipei-in-July
day: sunrise ~5:10, sunset ~18:45, min 26.6, max 34.8 (Table S3-adjacent
numbers, not the real climate-normal values -- picked for a wide, easy-to-
reason-about spread)."""

from __future__ import annotations

from app.diurnal_temperature import estimate_temperature_at_hour, unix_timestamp_to_local_hour

_SUNRISE = 5.17
_SUNSET = 18.75
_T_MIN = 26.6
_T_MAX = 34.8


def test_temperature_at_sunrise_is_close_to_the_daily_minimum():
    at_sunrise = estimate_temperature_at_hour(_SUNRISE, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    assert abs(at_sunrise - _T_MIN) < 0.1


def test_temperature_rises_through_the_morning():
    early = estimate_temperature_at_hour(7.0, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    late_morning = estimate_temperature_at_hour(11.0, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    assert _T_MIN < early < late_morning


def test_peak_temperature_occurs_after_solar_noon_not_at_noon():
    solar_noon = (_SUNRISE + _SUNSET) / 2
    at_noon = estimate_temperature_at_hour(solar_noon, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    at_1pm = estimate_temperature_at_hour(13.0, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    assert at_1pm > at_noon  # afternoon peak lags solar noon, per Parton & Logan (1981)


def test_daytime_never_exceeds_the_daily_maximum():
    for hour in [h * 0.5 for h in range(int(_SUNRISE * 2), int(_SUNSET * 2))]:
        assert estimate_temperature_at_hour(hour, _SUNRISE, _SUNSET, _T_MIN, _T_MAX) <= _T_MAX + 0.01


def test_temperature_falls_through_the_evening():
    early_evening = estimate_temperature_at_hour(19.5, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    late_evening = estimate_temperature_at_hour(23.0, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    assert early_evening > late_evening > _T_MIN


def test_temperature_before_sunrise_continues_the_previous_nights_decay():
    just_before_sunrise = estimate_temperature_at_hour(4.5, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    midnight = estimate_temperature_at_hour(0.0, _SUNRISE, _SUNSET, _T_MIN, _T_MAX)
    # still cooling toward the minimum as sunrise approaches
    assert _T_MIN <= just_before_sunrise < midnight


def test_never_goes_below_the_daily_minimum():
    for hour in [h * 0.5 for h in range(0, 48)]:
        assert estimate_temperature_at_hour(hour, _SUNRISE, _SUNSET, _T_MIN, _T_MAX) >= _T_MIN - 0.01


def test_unix_timestamp_to_local_hour_handles_a_positive_utc_offset():
    # 2026-01-01T00:00:00Z at UTC+8 (Taipei) is 08:00 local.
    assert unix_timestamp_to_local_hour(1767225600, 8 * 3600) == 8.0


def test_unix_timestamp_to_local_hour_wraps_past_midnight():
    # 2026-01-01T23:00:00Z at UTC+9 (Tokyo) is 08:00 local the next day.
    assert unix_timestamp_to_local_hour(1767225600 + 23 * 3600, 9 * 3600) == 8.0

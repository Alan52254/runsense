"""Diurnal (time-of-day) air temperature model, after Parton WJ, Logan JA
(1981) "A model for diurnal variation in soil and air temperature."
Agricultural Meteorology, 23, 205-216.

The model needs only four numbers for a given day: that day's minimum and
maximum temperature, and its sunrise/sunset times. Daytime temperature
(sunrise to sunset) follows a truncated sine wave rising from T_min at
sunrise to T_max shortly after solar noon; nighttime temperature (sunset to
next sunrise) decays exponentially from the sunset temperature back down
toward T_min. This lets RunSense estimate "what's it like at 6am / noon /
7pm today" from the same handful of numbers OpenWeatherMap's free current-
weather endpoint already returns for sunrise/sunset, combined with a
climate-normal min/max (see app/climate_normals.py) -- no forecast API call.

Constants A, B, C below are the model's own default parameters (time lag of
peak temperature after solar noon, nighttime decay rate, and time lag of
minimum temperature after sunrise, respectively), taken from the reference
implementation in the R package `weaana` (an existing open-source port of
this same 1981 model): https://github.com/byzheng/weaana, R/diurnal.R.
"""

from __future__ import annotations

import math

_LAG_HOURS_A = 1.5  # hours after solar noon that the daily peak occurs
_NIGHT_DECAY_B = 4.0  # controls how fast temperature falls overnight
_MIN_LAG_HOURS_C = 1.0  # hours after sunrise that the daily minimum occurs


def estimate_temperature_at_hour(
    hour: float,
    sunrise_hour: float,
    sunset_hour: float,
    t_min: float,
    t_max: float,
) -> float:
    """°C at local clock `hour` (0-24, may be fractional), given that day's
    sunrise/sunset (also 0-24) and min/max temperature.

    `t_min`/`t_max` are treated as constant across today, tonight, and
    tomorrow morning -- reasonable when they come from a monthly climate
    normal (which doesn't have a "yesterday" or "tomorrow" value distinct
    from "today" in the first place), less so from a single day's true
    forecast extremes, which this function isn't fed here regardless (see
    the module docstring).
    """
    day_length = sunset_hour - sunrise_hour
    night_length = 24.0 - day_length

    if sunrise_hour <= hour <= sunset_hour:
        hours_since_sunrise = hour - sunrise_hour
        return (t_max - t_min) * math.sin(
            math.pi * hours_since_sunrise / (day_length + 2 * _LAG_HOURS_A)
        ) + t_min

    # Nighttime: hours since the most recent sunset, whether that was later
    # today (hour > sunset) or still "yesterday" by clock time (hour < sunrise).
    hours_since_sunset = (hour - sunset_hour) if hour > sunset_hour else (hour + 24.0 - sunset_hour)

    hours_from_sunrise_to_sunset_minus_lag = day_length - _MIN_LAG_HOURS_C
    temperature_at_sunset = (t_max - t_min) * math.sin(
        math.pi * hours_from_sunrise_to_sunset_minus_lag / (day_length + 2 * _LAG_HOURS_A)
    ) + t_min

    return t_min + (temperature_at_sunset - t_min) * math.exp(
        -_NIGHT_DECAY_B * hours_since_sunset / night_length
    )


def unix_timestamp_to_local_hour(timestamp: int, utc_offset_seconds: int) -> float:
    """A Unix timestamp (as OpenWeatherMap returns sunrise/sunset) to an
    hour-of-day (0-24) in the given UTC offset, without needing the full
    IANA timezone -- OpenWeatherMap's current-weather response already
    carries `timezone` as a UTC offset in seconds alongside sunrise/sunset."""
    local_seconds_into_day = (timestamp + utc_offset_seconds) % 86400
    return local_seconds_into_day / 3600.0

"""1991-2020 monthly climate normals (mean/high/low, °C) for the cities
RunSense's demo personas run in. Sources, each retrieved 2026-08-25:

- Taipei: Taiwan Central Weather Administration, Taipei station, 1991-2020
  normals (https://www.cwa.gov.tw/V8/E/C/Statistics/monthlymean.html).
- Tokyo: Japan Meteorological Agency, Kitanomaru Park (Chiyoda) station,
  1991-2020 normals (https://www.data.jma.go.jp/stats/data/en/normal/normal.html,
  station 47662/97120).
- London: UK Met Office, Heathrow station, 1991-2020 normals.

These are climatological *normals* -- "what's typical this time of year" --
not a forecast for today. See app/weather_pace.py for how today's actual
reading gets compared against these, and app/diurnal_temperature.py for how
they're combined with today's real sunrise/sunset to estimate temperature
at a given hour.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonthNormal:
    mean_c: float
    high_c: float
    low_c: float


# Indexed 1-12 (January-December), matching datetime.month.
_TAIPEI: dict[int, MonthNormal] = {
    1: MonthNormal(16.4, 19.4, 14.2),
    2: MonthNormal(16.9, 20.3, 14.4),
    3: MonthNormal(18.8, 22.7, 16.0),
    4: MonthNormal(22.3, 26.4, 19.3),
    5: MonthNormal(25.6, 29.7, 22.6),
    6: MonthNormal(28.2, 32.7, 25.1),
    7: MonthNormal(29.9, 34.8, 26.6),
    8: MonthNormal(29.5, 34.2, 26.4),
    9: MonthNormal(27.7, 31.5, 25.0),
    10: MonthNormal(24.6, 27.6, 22.4),
    11: MonthNormal(21.9, 24.8, 19.7),
    12: MonthNormal(18.2, 21.0, 16.0),
}

_TOKYO: dict[int, MonthNormal] = {
    1: MonthNormal(5.4, 9.8, 1.2),
    2: MonthNormal(6.1, 10.9, 2.1),
    3: MonthNormal(9.4, 14.2, 5.0),
    4: MonthNormal(14.3, 19.4, 9.8),
    5: MonthNormal(18.8, 23.6, 14.6),
    6: MonthNormal(21.9, 26.1, 18.5),
    7: MonthNormal(25.7, 29.9, 22.4),
    8: MonthNormal(26.9, 31.3, 23.5),
    9: MonthNormal(23.3, 27.5, 20.3),
    10: MonthNormal(18.0, 22.0, 14.8),
    11: MonthNormal(12.5, 16.7, 8.8),
    12: MonthNormal(7.7, 12.0, 3.8),
}

_LONDON: dict[int, MonthNormal] = {
    1: MonthNormal(5.6, 8.4, 2.7),
    2: MonthNormal(5.8, 9.0, 2.7),
    3: MonthNormal(7.9, 11.7, 4.1),
    4: MonthNormal(10.5, 15.0, 6.0),
    5: MonthNormal(13.7, 18.4, 9.1),
    6: MonthNormal(16.8, 21.6, 12.0),
    7: MonthNormal(19.0, 23.9, 14.2),
    8: MonthNormal(18.7, 23.4, 14.1),
    9: MonthNormal(15.9, 20.2, 11.6),
    10: MonthNormal(12.3, 15.8, 8.8),
    11: MonthNormal(8.4, 11.5, 5.3),
    12: MonthNormal(5.9, 8.8, 3.1),
}

# Keyed by the same city strings athlete_profiles.city / DEMO_CREDENTIALS
# already use. A city typed freely by an athlete (ProfileSettings' city
# field is free text) that isn't in this table simply gets no climate-normal
# features -- see weather_pace.py and diurnal_temperature.py, both of which
# treat a missing entry as "skip this layer," never as an error.
_TABLE: dict[str, dict[int, MonthNormal]] = {
    "taipei": _TAIPEI,
    "臺北市": _TAIPEI,
    "台北市": _TAIPEI,
    "tokyo": _TOKYO,
    "東京": _TOKYO,
    "london": _LONDON,
    "倫敦": _LONDON,
}


def get_climate_normal(city: str | None, month: int) -> MonthNormal | None:
    if not city:
        return None
    months = _TABLE.get(city.strip()) or _TABLE.get(city.strip().lower())
    return months.get(month) if months else None

"""Hourly weather forecast for a city, for planning the coming week.

Open-Meteo's free forecast (no key) covers well past a 7-day planning
horizon. Like app/weather_client, this never raises: any failure returns
None and the caller falls back to the climate estimate, labelled as such.
A forecast is cached in-process for 30 minutes so redrafting a week does not
refetch it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from app.weather_client import _KNOWN_CITY_COORDINATES

logger = logging.getLogger("app.weather_forecast")

PROVIDER = "open-meteo"
_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT_S = 4.0
_CACHE_S = 30 * 60
_cache: dict[str, tuple[float, "HourlyForecast"]] = {}


@dataclass(frozen=True)
class HourlyForecast:
    provider: str
    fetched_at: str  # ISO, UTC
    # (local date, local hour) -> (°C, relative humidity %, wind km/h)
    hours: dict[tuple[date, int], tuple[float, float | None, float | None]]

    def at(self, day: date, hour: int) -> tuple[float, float | None, float | None] | None:
        return self.hours.get((day, hour))


def fetch(city: str | None) -> HourlyForecast | None:
    if not city:
        return None
    key = city.strip().lower()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_S:
        return hit[1]
    coords = _KNOWN_CITY_COORDINATES.get(key) or _KNOWN_CITY_COORDINATES.get(city.strip())
    if coords is None:
        return None
    try:
        resp = httpx.get(_URL, params={
            "latitude": coords[0], "longitude": coords[1],
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "forecast_days": 9, "timezone": "auto"}, timeout=_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        hourly = resp.json()["hourly"]
    except Exception as exc:  # network, JSON, shape -- all mean "no forecast"
        logger.warning("weather_forecast_unavailable city=%s err=%s", city, exc)
        return None
    hours: dict[tuple[date, int], tuple[float, float | None, float | None]] = {}
    for i, stamp in enumerate(hourly.get("time", [])):
        temp = hourly["temperature_2m"][i]
        if temp is None:
            continue
        local = datetime.fromisoformat(stamp)  # already local (timezone=auto)
        humid = (hourly.get("relative_humidity_2m") or [None] * (i + 1))[i]
        wind = (hourly.get("wind_speed_10m") or [None] * (i + 1))[i]
        hours[(local.date(), local.hour)] = (float(temp), humid, wind)
    if not hours:
        return None
    result = HourlyForecast(PROVIDER, datetime.now(UTC).isoformat(timespec="seconds"), hours)
    _cache[key] = (time.monotonic(), result)
    return result

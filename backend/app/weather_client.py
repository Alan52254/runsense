"""OpenWeatherMap HTTP client. See design.md Decision 1/2/10: short timeout,
never raises past this module -- callers get None on any failure and decide
the fallback state themselves (weather.py's LIVE/CACHED/STALE/UNAVAILABLE
logic), rather than this module encoding retry/fallback policy itself.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

_TIMEOUT_SECONDS = 3.0
_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"


class LiveWeatherReading(BaseModel):
    temperature_c: float
    humidity_pct: float
    observed_at: datetime
    # For app/diurnal_temperature.py's time-of-day estimate -- OpenWeatherMap's
    # current-weather response already carries these at no extra cost (no
    # forecast endpoint needed).
    sunrise: datetime
    sunset: datetime
    utc_offset_seconds: int


def fetch_live_weather(city: str) -> LiveWeatherReading | None:
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        return None
    try:
        response = httpx.get(
            _BASE_URL,
            params={"q": city, "appid": api_key, "units": "metric"},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        return LiveWeatherReading(
            temperature_c=body["main"]["temp"],
            humidity_pct=body["main"]["humidity"],
            observed_at=datetime.fromtimestamp(body["dt"], tz=timezone.utc),
            sunrise=datetime.fromtimestamp(body["sys"]["sunrise"], tz=timezone.utc),
            sunset=datetime.fromtimestamp(body["sys"]["sunset"], tz=timezone.utc),
            utc_offset_seconds=body["timezone"],
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None

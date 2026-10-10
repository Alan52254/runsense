"""OpenWeatherMap HTTP client. See design.md Decision 1/2/10: short timeout,
never raises past this module -- callers get None on any failure and decide
the fallback state themselves (weather.py's LIVE/CACHED/STALE/UNAVAILABLE
logic), rather than this module encoding retry/fallback policy itself.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel

logger = logging.getLogger("app.weather_client")

_TIMEOUT_SECONDS = 3.5
_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

_KNOWN_CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "taipei": (25.0330, 121.5654),
    "台北": (25.0330, 121.5654),
    "臺北": (25.0330, 121.5654),
    "台北市": (25.0330, 121.5654),
    "臺北市": (25.0330, 121.5654),
    "tokyo": (35.6762, 139.6503),
    "東京": (35.6762, 139.6503),
    "東京都": (35.6762, 139.6503),
    "london": (51.5074, -0.1278),
    "倫敦": (51.5074, -0.1278),
    "hsinchu": (24.8138, 120.9675),
    "新竹": (24.8138, 120.9675),
    "新竹市": (24.8138, 120.9675),
    "taichung": (24.1477, 120.6736),
    "台中": (24.1477, 120.6736),
    "臺中": (24.1477, 120.6736),
    "台中市": (24.1477, 120.6736),
    "臺中市": (24.1477, 120.6736),
    "tainan": (22.9997, 120.2270),
    "台南": (22.9997, 120.2270),
    "臺南": (22.9997, 120.2270),
    "台南市": (22.9997, 120.2270),
    "臺南市": (22.9997, 120.2270),
    "kaohsiung": (22.6273, 120.3014),
    "高雄": (22.6273, 120.3014),
    "高雄市": (22.6273, 120.3014),
}


class LiveWeatherReading(BaseModel):
    temperature_c: float
    humidity_pct: float
    observed_at: datetime
    # For app/diurnal_temperature.py's time-of-day estimate -- OpenWeatherMap/Open-Meteo
    # current-weather response already carries these at no extra cost.
    sunrise: datetime
    sunset: datetime
    utc_offset_seconds: int


def _fetch_open_meteo(city: str) -> LiveWeatherReading | None:
    norm_city = city.strip().lower()
    coords = _KNOWN_CITY_COORDINATES.get(norm_city) or _KNOWN_CITY_COORDINATES.get(city.strip())
    lat, lon = (0.0, 0.0)

    if coords is not None:
        lat, lon = coords
    else:
        # Fallback to Open-Meteo geocoding
        try:
            geo_resp = httpx.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city.strip(), "count": 1},
                timeout=_TIMEOUT_SECONDS,
            )
            if geo_resp.status_code == 200:
                results = geo_resp.json().get("results")
                if results:
                    lat = float(results[0]["latitude"])
                    lon = float(results[0]["longitude"])
                else:
                    return None
            else:
                return None
        except Exception:
            return None

    try:
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m",
                "daily": "sunrise,sunset",
                "timezone": "auto",
            },
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        utc_offset_seconds = int(data.get("utc_offset_seconds", 0))
        tz = timezone(timedelta(seconds=utc_offset_seconds))

        current = data["current"]
        temperature_c = float(current["temperature_2m"])
        humidity_pct = float(current["relative_humidity_2m"])
        observed_at = datetime.fromisoformat(current["time"]).replace(tzinfo=tz).astimezone(timezone.utc)

        daily = data.get("daily", {})
        sunrises = daily.get("sunrise", [])
        sunsets = daily.get("sunset", [])

        if sunrises and sunsets:
            sunrise = datetime.fromisoformat(sunrises[0]).replace(tzinfo=tz).astimezone(timezone.utc)
            sunset = datetime.fromisoformat(sunsets[0]).replace(tzinfo=tz).astimezone(timezone.utc)
        else:
            now_utc = datetime.now(timezone.utc)
            sunrise = now_utc.replace(hour=6, minute=0, second=0, microsecond=0)
            sunset = now_utc.replace(hour=18, minute=0, second=0, microsecond=0)

        return LiveWeatherReading(
            temperature_c=round(temperature_c, 1),
            humidity_pct=round(humidity_pct, 1),
            observed_at=observed_at,
            sunrise=sunrise,
            sunset=sunset,
            utc_offset_seconds=utc_offset_seconds,
        )
    except Exception as exc:
        logger.warning("open_meteo_fetch_failed city=%s reason=%s", city, type(exc).__name__)
        return None


def fetch_live_weather(city: str) -> LiveWeatherReading | None:
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if api_key:
        try:
            response = httpx.get(
                _BASE_URL,
                params={"q": city, "appid": api_key, "units": "metric"},
                timeout=_TIMEOUT_SECONDS,
            )
            if response.status_code == 200:
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
            pass

    # Open-Meteo fallback provides accurate live weather even when no OpenWeather key is set
    return _fetch_open_meteo(city)


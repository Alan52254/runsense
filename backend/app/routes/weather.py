from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.schemas import WeatherResponse
from app.weather_client import fetch_live_weather
from app.weather_pace import pace_adjustment_sec_per_km

router = APIRouter()

# design.md Decision 2: 10-minute cache freshness, 3-hour staleness ceiling.
_CACHED_WINDOW = timedelta(minutes=10)
_STALE_WINDOW = timedelta(hours=3)

_SELECT_CITY = text("SELECT city FROM athlete_profiles WHERE user_id = :user_id")
_SELECT_CACHE = text(
    "SELECT temperature_c, humidity_pct, provider_observed_at, fetched_at "
    "FROM weather_cache WHERE city = :city"
)
_UPSERT_CACHE = text(
    "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at) "
    "VALUES (:city, :temperature_c, :humidity_pct, :provider_observed_at, :fetched_at) "
    "ON CONFLICT (city) DO UPDATE SET "
    "temperature_c = EXCLUDED.temperature_c, humidity_pct = EXCLUDED.humidity_pct, "
    "provider_observed_at = EXCLUDED.provider_observed_at, fetched_at = EXCLUDED.fetched_at"
)


def _empty_response(state: str, city: str | None) -> WeatherResponse:
    return WeatherResponse(
        state=state,
        city=city,
        temperature_c=None,
        humidity_pct=None,
        observed_at=None,
        pace_adjustment_sec_per_km=None,
    )


@router.get("/weather", response_model=WeatherResponse)
def get_weather(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> WeatherResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        city = tx.execute(_SELECT_CITY, {"user_id": actor_id_raw}).scalar_one_or_none()
        if not city:
            return _empty_response("UNAVAILABLE", None)

        cache_row = tx.execute(_SELECT_CACHE, {"city": city}).first()
        now = datetime.now(timezone.utc)

        if cache_row is not None and now - cache_row.fetched_at < _CACHED_WINDOW:
            return _cache_response("CACHED", city, cache_row)

        live = fetch_live_weather(city)
        if live is not None:
            tx.execute(
                _UPSERT_CACHE,
                {
                    "city": city,
                    "temperature_c": live.temperature_c,
                    "humidity_pct": live.humidity_pct,
                    "provider_observed_at": live.observed_at,
                    "fetched_at": now,
                },
            )
            return WeatherResponse(
                state="LIVE",
                city=city,
                temperature_c=live.temperature_c,
                humidity_pct=live.humidity_pct,
                observed_at=live.observed_at,
                pace_adjustment_sec_per_km=pace_adjustment_sec_per_km(
                    live.temperature_c, live.humidity_pct
                ),
            )

        if cache_row is not None and now - cache_row.fetched_at < _STALE_WINDOW:
            return _cache_response("STALE", city, cache_row)

        return _empty_response("UNAVAILABLE", city)


def _cache_response(state: str, city: str, cache_row: Any) -> WeatherResponse:
    return WeatherResponse(
        state=state,
        city=city,
        temperature_c=float(cache_row.temperature_c),
        humidity_pct=float(cache_row.humidity_pct),
        observed_at=cache_row.provider_observed_at,
        pace_adjustment_sec_per_km=pace_adjustment_sec_per_km(
            float(cache_row.temperature_c), float(cache_row.humidity_pct)
        ),
    )

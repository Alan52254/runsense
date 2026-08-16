"""DB-dependent tests for GET /weather. Live provider calls are mocked via
app.routes.weather.fetch_live_weather -- no real OpenWeatherMap key needed.
See spec.md's weather-conditions requirements and tasks.md 3.5-3.10."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.routes import weather as weather_module
from app.weather_client import LiveWeatherReading
from conftest import requires_db


def _insert_athlete_with_city(admin_engine, city: str | None):
    athlete_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": athlete_id, "email": f"{athlete_id}@example.test"},
        )
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone, city) VALUES (:id, 'Asia/Taipei', :city)"),
            {"id": athlete_id, "city": city},
        )
    return athlete_id


@requires_db
def test_no_city_set_is_unavailable_and_never_calls_the_provider(
    make_client, admin_engine, monkeypatch
):
    athlete_id = _insert_athlete_with_city(admin_engine, city=None)
    called = {"count": 0}
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: called.__setitem__("count", called["count"] + 1) or None)

    response = make_client(actor_id=str(athlete_id)).get("/weather")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "UNAVAILABLE"
    assert body["city"] is None
    assert called["count"] == 0


@requires_db
def test_live_success_returns_live_and_populates_the_cache(make_client, admin_engine, monkeypatch):
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei")
    monkeypatch.setattr(
        weather_module,
        "fetch_live_weather",
        lambda city: LiveWeatherReading(temperature_c=30.0, humidity_pct=70.0, observed_at=datetime.now(timezone.utc)),
    )

    response = make_client(actor_id=str(athlete_id)).get("/weather")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "LIVE"
    assert body["temperature_c"] == 30.0
    assert body["pace_adjustment_sec_per_km"] is not None

    with admin_engine.connect() as conn:
        cached = conn.execute(text("SELECT temperature_c FROM weather_cache WHERE city = 'Taipei'")).scalar_one()
    assert float(cached) == 30.0


@requires_db
def test_fresh_cache_is_served_without_a_live_call(make_client, admin_engine, monkeypatch):
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at) "
                "VALUES ('Taipei', 28.0, 60.0, now(), now())"
            )
        )
    called = {"count": 0}
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: called.__setitem__("count", called["count"] + 1) or None)

    response = make_client(actor_id=str(athlete_id)).get("/weather")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "CACHED"
    assert body["temperature_c"] == 28.0
    assert called["count"] == 0


@requires_db
def test_live_failure_with_recent_cache_returns_stale(make_client, admin_engine, monkeypatch):
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei")
    old_fetch = datetime.now(timezone.utc) - timedelta(minutes=30)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at) "
                "VALUES ('Taipei', 27.0, 55.0, :fetched, :fetched)"
            ),
            {"fetched": old_fetch},
        )
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: None)

    response = make_client(actor_id=str(athlete_id)).get("/weather")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "STALE"
    assert body["temperature_c"] == 27.0


@requires_db
def test_live_failure_with_no_cache_returns_unavailable(make_client, admin_engine, monkeypatch):
    athlete_id = _insert_athlete_with_city(admin_engine, city="Osaka")
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: None)

    response = make_client(actor_id=str(athlete_id)).get("/weather")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "UNAVAILABLE"
    assert body["temperature_c"] is None


@requires_db
def test_two_athletes_same_city_share_one_cache_row_no_leak(make_client, admin_engine, monkeypatch):
    athlete_a = _insert_athlete_with_city(admin_engine, city="Taipei")
    athlete_b = _insert_athlete_with_city(admin_engine, city="Taipei")
    calls = {"count": 0}

    def _fetch(city):
        calls["count"] += 1
        return LiveWeatherReading(temperature_c=25.0, humidity_pct=50.0, observed_at=datetime.now(timezone.utc))

    monkeypatch.setattr(weather_module, "fetch_live_weather", _fetch)

    first = make_client(actor_id=str(athlete_a)).get("/weather")
    assert first.json()["state"] == "LIVE"
    assert calls["count"] == 1

    second = make_client(actor_id=str(athlete_b)).get("/weather")
    assert second.json()["state"] == "CACHED"
    assert calls["count"] == 1  # second athlete reused athlete_a's fetch -- no per-athlete field leaked
    assert second.json()["temperature_c"] == 25.0

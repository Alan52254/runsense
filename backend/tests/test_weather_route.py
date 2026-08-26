"""DB-dependent tests for GET /weather. Live provider calls are mocked via
app.routes.weather.fetch_live_weather -- no real OpenWeatherMap key needed.
See spec.md's weather-conditions requirements and tasks.md 3.5-3.10."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.climate_normals import get_climate_normal
from app.diurnal_temperature import estimate_temperature_at_hour
from app.routes import weather as weather_module
from app.weather_client import LiveWeatherReading
from conftest import requires_db

_TAIPEI_UTC_OFFSET = 8 * 3600


def _mock_reading(temperature_c: float, humidity_pct: float) -> LiveWeatherReading:
    """A plausible Taipei reading (sunrise ~06:00, sunset ~18:00 local) --
    populated so tests exercise the climate-normal/time-of-day path too,
    not just the bare temperature/humidity fields."""
    now = datetime.now(timezone.utc)
    today_utc_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return LiveWeatherReading(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        observed_at=now,
        sunrise=today_utc_midnight + timedelta(hours=6 - 8),  # local 06:00 at UTC+8
        sunset=today_utc_midnight + timedelta(hours=18 - 8),  # local 18:00 at UTC+8
        utc_offset_seconds=_TAIPEI_UTC_OFFSET,
    )


def _reading_with_fixed_suntimes(
    temperature_c: float, sunrise_utc: datetime, sunset_utc: datetime
) -> LiveWeatherReading:
    """Like _mock_reading, but sunrise/sunset are caller-supplied fixed UTC
    instants instead of derived from real wall-clock "today" -- for tests
    that also freeze the route's clock (see _freeze_clock) and need the two
    to agree on what day/hour it is."""
    return LiveWeatherReading(
        temperature_c=temperature_c,
        humidity_pct=70.0,
        observed_at=sunrise_utc,
        sunrise=sunrise_utc,
        sunset=sunset_utc,
        utc_offset_seconds=_TAIPEI_UTC_OFFSET,
    )


def _freeze_clock(monkeypatch, when: datetime) -> None:
    """Freeze weather_module's `datetime.now()` to `when`, so a test doesn't
    depend on what time of day the suite happens to run."""

    class _FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return when

    monkeypatch.setattr(weather_module, "datetime", _FixedClock)


def _insert_athlete_with_city(admin_engine, city: str | None, sex: str | None = None):
    athlete_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": athlete_id, "email": f"{athlete_id}@example.test"},
        )
        conn.execute(
            text(
                "INSERT INTO athlete_profiles (user_id, timezone, city, sex) "
                "VALUES (:id, 'Asia/Taipei', :city, :sex)"
            ),
            {"id": athlete_id, "city": city, "sex": sex},
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
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(30.0, 70.0))

    response = make_client(actor_id=str(athlete_id)).get("/weather")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "LIVE"
    assert body["temperature_c"] == 30.0
    assert body["speed_loss_pct"] is not None

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
        return _mock_reading(25.0, 50.0)

    monkeypatch.setattr(weather_module, "fetch_live_weather", _fetch)

    first = make_client(actor_id=str(athlete_a)).get("/weather")
    assert first.json()["state"] == "LIVE"
    assert calls["count"] == 1

    second = make_client(actor_id=str(athlete_b)).get("/weather")
    assert second.json()["state"] == "CACHED"
    assert calls["count"] == 1  # second athlete reused athlete_a's fetch -- no per-athlete field leaked
    assert second.json()["temperature_c"] == 25.0


@requires_db
def test_speed_loss_pct_differs_by_athlete_sex_at_the_same_cached_temperature(
    make_client, admin_engine, monkeypatch
):
    # Same city/temperature, different sex on file -- the derived
    # speed_loss_pct must reflect *this* athlete's curve, not a value
    # baked into the shared weather_cache row (which only stores raw
    # temperature/humidity, never the derived percentage).
    male_athlete = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    female_athlete = _insert_athlete_with_city(admin_engine, city="Taipei", sex="female")
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(30.0, 70.0))

    male_body = make_client(actor_id=str(male_athlete)).get("/weather").json()
    female_body = make_client(actor_id=str(female_athlete)).get("/weather").json()

    assert male_body["state"] == "LIVE"
    assert female_body["state"] == "CACHED"  # same city, second request reuses the cache row
    assert male_body["speed_loss_pct"] != female_body["speed_loss_pct"]


@requires_db
def test_climate_normal_city_colder_than_normal_gets_discounted(make_client, admin_engine, monkeypatch):
    # Taipei is in app/climate_normals.py. The route picks the normal for
    # *today's real* local month (see _build_response's local_now), so this
    # looks up that same month directly rather than assuming a season --
    # 8°C below normal is a cool day whichever month it is, so an athlete
    # there is presumably still heat-acclimatized to worse, and the raw El
    # Helou penalty should be discounted, not applied at face value.
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    this_month_normal = get_climate_normal("Taipei", datetime.now(timezone.utc).month)
    assert this_month_normal is not None
    cool_reading = this_month_normal.mean_c - 8.0
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(cool_reading, 70.0))

    body = make_client(actor_id=str(athlete_id)).get("/weather").json()

    assert body["climate_normal_temperature_c"] == this_month_normal.mean_c
    assert body["speed_loss_pct_unadjusted"] is not None
    assert body["speed_loss_pct"] < body["speed_loss_pct_unadjusted"]


@requires_db
def test_climate_normal_city_hotter_than_normal_gets_amplified(make_client, admin_engine, monkeypatch):
    # Same city/month, but now a reading well above normal -- an anomalous
    # heat spike, which should amplify the raw penalty.
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    this_month_normal = get_climate_normal("Taipei", datetime.now(timezone.utc).month)
    assert this_month_normal is not None
    hot_reading = this_month_normal.mean_c + 8.0
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(hot_reading, 70.0))

    body = make_client(actor_id=str(athlete_id)).get("/weather").json()

    assert body["speed_loss_pct"] > body["speed_loss_pct_unadjusted"]


@requires_db
def test_climate_normal_city_gets_three_time_of_day_estimates(make_client, admin_engine, monkeypatch):
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="female")
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(30.0, 70.0))

    body = make_client(actor_id=str(athlete_id)).get("/weather").json()

    labels = [e["label"] for e in body["time_of_day_estimates"]]
    assert labels == ["morning", "midday", "evening"]
    for estimate in body["time_of_day_estimates"]:
        assert estimate["temperature_c"] is not None
        assert estimate["speed_loss_pct"] is not None
    # Midday (solar-peak-adjacent) should read hotter than early morning.
    morning, midday, _evening = body["time_of_day_estimates"]
    assert midday["temperature_c"] > morning["temperature_c"]


@requires_db
def test_relative_to_normal_pct_differs_from_the_absolute_curve_for_a_climate_normal_city(
    make_client, admin_engine, monkeypatch
):
    # A day right at the local climate-normal mean should read as ~zero
    # deviation under speed_loss_pct_relative_to_normal, while the absolute
    # curve (speed_loss_pct_unadjusted, centered on the paper's ~6-10C
    # optimum) still reports a real penalty for a hot climate's normal day.
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    this_month_normal = get_climate_normal("Taipei", datetime.now(timezone.utc).month)
    assert this_month_normal is not None
    monkeypatch.setattr(
        weather_module, "fetch_live_weather", lambda city: _mock_reading(this_month_normal.mean_c, 70.0)
    )

    body = make_client(actor_id=str(athlete_id)).get("/weather").json()

    assert body["speed_loss_pct_relative_to_normal"] < body["speed_loss_pct_unadjusted"]


@requires_db
def test_relative_to_normal_reference_is_a_fixed_evening_hour_not_the_flat_monthly_mean(
    make_client, admin_engine, monkeypatch
):
    """climate_normal_reference_c should track what's climatologically
    typical for the assumed reference run hour (early evening -- see
    _REFERENCE_RUN_HOUR), not just this month's flat mean -- the two are
    measurably different numbers (Taipei's August evening-at-18:30 normal
    vs. its flat monthly mean, which blends in the hot midday peak), so a
    reading that exactly matches the mean should read differently under
    the two approaches. Uses a fixed clock (monkeypatching
    weather_module.datetime) so this doesn't depend on what time of day
    the test suite happens to run."""
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    this_month_normal = get_climate_normal("Taipei", 8)
    assert this_month_normal is not None
    reading = this_month_normal.mean_c

    # 06:00 / 18:00 local (UTC+8) on 2026-08-25, expressed in UTC so the
    # fixture doesn't depend on real wall-clock "today".
    sunrise_utc = datetime(2026, 8, 24, 22, 0, 0, tzinfo=timezone.utc)
    sunset_utc = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        weather_module, "fetch_live_weather", lambda city: _reading_with_fixed_suntimes(reading, sunrise_utc, sunset_utc)
    )
    # 18:30 local -- exactly the assumed reference hour itself, so any gap
    # between climate_normal_reference_c and the flat mean is due purely to
    # the fixed-hour fix, not to which hour the test happens to fire at.
    _freeze_clock(monkeypatch, datetime(2026, 8, 25, 10, 30, 0, tzinfo=timezone.utc))

    body = make_client(actor_id=str(athlete_id)).get("/weather").json()

    assert body["climate_normal_reference_c"] is not None
    assert abs(body["climate_normal_reference_c"] - this_month_normal.mean_c) > 1.5  # measurably different


@requires_db
def test_time_of_day_slots_compare_against_the_shared_reference_hour_not_each_other(
    make_client, admin_engine, monkeypatch
):
    """All time_of_day_estimates slots (and the "now" adjustment) must be
    directly comparable to each other -- a runner deciding between a
    morning and an evening run needs to see that they genuinely differ,
    not just whether today happens to be typical for whichever hour
    they're looking at. Proven here: when the actual reading exactly
    matches what's climatologically normal for the reference hour (early
    evening), the evening slot reads as ~0% while morning and midday --
    genuinely different temperatures in Taipei in August -- read as real,
    nonzero adjustments relative to that same evening reference.

    Taipei's August evening (~31.3C) is already past the El Helou curve's
    own measured optimum by a wide margin, so morning (~26.4C, closer to
    the curve's true ~3.75C P1 optimum for this male athlete) is a genuine
    pace BONUS relative to the hot evening reference -- a negative figure,
    not a cost -- while midday
    (~33.8C, further from the optimum than the evening) is a genuine
    extra cost, a positive figure. See weather_pace.py's
    speed_loss_pct_relative_to_normal docstring: this is a plain
    difference of two curve lookups, not a curve re-centered on the
    reference, so "further from the reference" only costs more when it's
    also further from the paper's actual optimum -- moving from a hot
    reference toward that optimum is a bonus, not a cost."""
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    this_month_normal = get_climate_normal("Taipei", 8)
    assert this_month_normal is not None

    sunrise_utc = datetime(2026, 8, 24, 22, 0, 0, tzinfo=timezone.utc)  # 06:00 local
    sunset_utc = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)  # 18:00 local
    sunrise_hour, sunset_hour = 6.0, 18.0
    reference_hour = weather_module._REFERENCE_RUN_HOUR
    reading = estimate_temperature_at_hour(
        reference_hour, sunrise_hour, sunset_hour, this_month_normal.low_c, this_month_normal.high_c
    )
    monkeypatch.setattr(
        weather_module, "fetch_live_weather", lambda city: _reading_with_fixed_suntimes(reading, sunrise_utc, sunset_utc)
    )
    # 18:30 local -- matches the reference hour, so today's anomaly (actual
    # minus climatological-now) is ~0 and the reading is exactly what a
    # normal evening looks like.
    _freeze_clock(monkeypatch, datetime(2026, 8, 25, 10, 30, 0, tzinfo=timezone.utc))

    body = make_client(actor_id=str(athlete_id)).get("/weather").json()

    slots = {slot["label"]: slot for slot in body["time_of_day_estimates"]}
    assert abs(slots["evening"]["speed_loss_pct"]) < 0.1  # matches the reference almost exactly
    assert slots["morning"]["speed_loss_pct"] < -0.1  # cooler than the evening reference -- a real bonus
    assert slots["midday"]["speed_loss_pct"] > 0.1  # hotter than the evening reference -- a real extra cost
    assert slots["morning"]["speed_loss_pct"] < slots["evening"]["speed_loss_pct"] < slots["midday"]["speed_loss_pct"]
    assert abs(body["climate_normal_reference_c"] - reading) < 0.05  # fixed reference, independent of wall-clock "now"


@requires_db
def test_segment_offsets_min_returns_one_estimate_per_offset_in_request_order(
    make_client, admin_engine, monkeypatch
):
    """?segment_offsets_min=... lets a client ask for the predicted
    temperature/pace impact at specific minutes-from-now points -- e.g. one
    per block of a multi-segment workout, using each block's estimated
    start time rather than only the three fixed time_of_day_estimates
    slots. This proves the same "compare against the fixed evening
    reference" property already established for time_of_day_estimates
    holds for caller-supplied offsets too: offset 0 (now = 06:00, a normal
    Taipei-August morning at ~26.4C) reads as a genuine BONUS relative to
    offset 750 (12.5h later = 18:30, exactly the reference hour, ~31.3C)
    -- morning is closer to the paper's true ~3.75C P1 optimum (this
    athlete is male) than the hot evening reference is, so the paper's own
    curve says it costs less, not more (see weather_pace.py's
    speed_loss_pct_relative_to_normal docstring) -- and the response
    preserves request order/count/values rather than sorting or
    deduplicating."""
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    this_month_normal = get_climate_normal("Taipei", 8)
    assert this_month_normal is not None

    sunrise_utc = datetime(2026, 8, 24, 22, 0, 0, tzinfo=timezone.utc)  # 06:00 local
    sunset_utc = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)  # 18:00 local
    # A completely normal morning: the reading matches morning's own
    # climatological normal exactly, so today's anomaly is ~0.
    reading = this_month_normal.low_c
    monkeypatch.setattr(
        weather_module, "fetch_live_weather", lambda city: _reading_with_fixed_suntimes(reading, sunrise_utc, sunset_utc)
    )
    _freeze_clock(monkeypatch, datetime(2026, 8, 24, 22, 0, 0, tzinfo=timezone.utc))  # 06:00 local

    response = make_client(actor_id=str(athlete_id)).get(
        "/weather", params={"segment_offsets_min": [750, 0]}  # deliberately out of order
    )
    assert response.status_code == 200
    estimates = response.json()["segment_estimates"]

    assert [e["offset_min"] for e in estimates] == [750, 0]  # request order preserved, not sorted
    at_750, at_0 = estimates
    assert abs(at_750["speed_loss_pct"]) < 0.1  # 750min later = 18:30, the reference hour itself
    assert at_0["speed_loss_pct"] < -0.1  # now = 06:00, cooler than the evening reference -- a real bonus
    assert at_0["speed_loss_pct"] < at_750["speed_loss_pct"]


@requires_db
def test_segment_offsets_min_is_empty_when_not_requested(make_client, admin_engine, monkeypatch):
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(30.0, 70.0))

    body = make_client(actor_id=str(athlete_id)).get("/weather").json()

    assert body["segment_estimates"] == []


@requires_db
def test_segment_offsets_min_negative_values_are_dropped_not_rejected(
    make_client, admin_engine, monkeypatch
):
    """An optional, additive parameter shouldn't 422 the whole weather
    lookup over one bad value -- invalid offsets are silently dropped
    instead, so the base weather data still comes back."""
    athlete_id = _insert_athlete_with_city(admin_engine, city="Taipei", sex="male")
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(30.0, 70.0))

    response = make_client(actor_id=str(athlete_id)).get(
        "/weather", params={"segment_offsets_min": [-10, 30]}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["state"] == "LIVE"
    assert [e["offset_min"] for e in body["segment_estimates"]] == [30]


@requires_db
def test_city_without_a_climate_normal_entry_gets_no_time_of_day_estimates(
    make_client, admin_engine, monkeypatch
):
    athlete_id = _insert_athlete_with_city(admin_engine, city="Osaka", sex="male")
    monkeypatch.setattr(weather_module, "fetch_live_weather", lambda city: _mock_reading(30.0, 70.0))

    body = make_client(actor_id=str(athlete_id)).get(
        "/weather", params={"segment_offsets_min": [0, 30]}
    ).json()

    assert body["state"] == "LIVE"
    assert body["climate_normal_temperature_c"] is None
    assert body["time_of_day_estimates"] == []
    assert body["segment_estimates"] == []  # degrades gracefully even when offsets were requested
    # Layer 1 (the base curve) still works even without a climate-normal
    # entry -- only the acclimatization/diurnal layers degrade gracefully.
    assert body["speed_loss_pct"] == body["speed_loss_pct_unadjusted"]

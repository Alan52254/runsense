from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection, text

from app.climate_normals import MonthNormal, get_climate_normal
from app.db import actor_transaction, get_connection
from app.diurnal_temperature import estimate_temperature_at_hour, unix_timestamp_to_local_hour
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.schemas import SegmentTemperatureEstimate, TimeOfDayTemperatureEstimate, WeatherResponse
from app.weather_client import fetch_live_weather
from app.weather_pace import acclimatization_multiplier, speed_loss_pct, speed_loss_pct_relative_to_normal

router = APIRouter()

# design.md Decision 2: 10-minute cache freshness, 3-hour staleness ceiling.
_CACHED_WINDOW = timedelta(minutes=10)
_STALE_WINDOW = timedelta(hours=3)

# Representative run times for the time_of_day_estimates -- not a claim
# about when any particular athlete runs, just three commonly-asked-about
# points in the day.
_TIME_OF_DAY_HOURS: list[tuple[str, float]] = [
    ("morning", 6.0),
    ("midday", 12.0),
    ("evening", 18.5),
]

# Coach-assigned and system-recommended paces are assumed to target a
# typical early-evening run -- the conventional window for avoiding midday
# heat, and the most defensible single assumption available since
# assignments don't currently record an intended time of day. Every
# relative-to-normal comparison below (the "now" figure, all three
# time-of-day slots, and the coach-pace adjustment) is measured against
# THIS SAME fixed hour's climatological normal, not whatever hour it
# happens to be right now -- comparing each hour against its own normal
# would make a perfectly ordinary midday read as "0% unusual" even though
# midday is still genuinely hotter than the evening the pace was
# calibrated for, silently losing exactly the signal a runner needs when
# deciding to run at an atypical time of day.
_REFERENCE_RUN_HOUR = 18.5

_SELECT_PROFILE = text("SELECT city, sex FROM athlete_profiles WHERE user_id = :user_id")
_SELECT_CACHE = text(
    "SELECT temperature_c, humidity_pct, provider_observed_at, fetched_at, "
    "sunrise_utc, sunset_utc, utc_offset_seconds "
    "FROM weather_cache WHERE city = :city"
)
_UPSERT_CACHE = text(
    "INSERT INTO weather_cache ("
    "  city, temperature_c, humidity_pct, provider_observed_at, fetched_at,"
    "  sunrise_utc, sunset_utc, utc_offset_seconds"
    ") VALUES ("
    "  :city, :temperature_c, :humidity_pct, :provider_observed_at, :fetched_at,"
    "  :sunrise_utc, :sunset_utc, :utc_offset_seconds"
    ") "
    "ON CONFLICT (city) DO UPDATE SET "
    "temperature_c = EXCLUDED.temperature_c, humidity_pct = EXCLUDED.humidity_pct, "
    "provider_observed_at = EXCLUDED.provider_observed_at, fetched_at = EXCLUDED.fetched_at, "
    "sunrise_utc = EXCLUDED.sunrise_utc, sunset_utc = EXCLUDED.sunset_utc, "
    "utc_offset_seconds = EXCLUDED.utc_offset_seconds"
)


def _empty_response(state: str, city: str | None) -> WeatherResponse:
    return WeatherResponse(
        state=state,
        city=city,
        temperature_c=None,
        humidity_pct=None,
        observed_at=None,
        speed_loss_pct=None,
        speed_loss_pct_unadjusted=None,
        speed_loss_pct_relative_to_normal=None,
        climate_normal_temperature_c=None,
        climate_normal_reference_c=None,
        time_of_day_estimates=[],
        segment_estimates=[],
    )


def _predicted_temperature_and_pct(
    hour: float,
    normal: MonthNormal,
    sunrise_hour: float,
    sunset_hour: float,
    anomaly: float,
    reference_c: float,
    sex: str | None,
) -> tuple[float, float]:
    """One hour's anomaly-carried predicted temperature (see
    _time_of_day_estimates' docstring for what `anomaly` carries forward)
    and its speed_loss_pct_relative_to_normal against the shared
    `reference_c` -- the one piece of math both _time_of_day_estimates and
    _segment_estimates are built from, so the two stay consistent with
    each other by construction rather than by keeping two copies in sync.
    `hour` is wrapped into 0-24 first since a segment offset can carry
    "now" past midnight (estimate_temperature_at_hour requires 0-24)."""
    wrapped_hour = hour % 24.0
    climatological_at_hour = estimate_temperature_at_hour(
        wrapped_hour, sunrise_hour, sunset_hour, normal.low_c, normal.high_c
    )
    estimated_temp = climatological_at_hour + anomaly
    relative_pct = speed_loss_pct_relative_to_normal(estimated_temp, reference_c, sex)
    return estimated_temp, relative_pct


def _time_of_day_estimates(
    normal: MonthNormal,
    sunrise_hour: float,
    sunset_hour: float,
    anomaly: float,
    sex: str | None,
    reference_c: float,
) -> list[TimeOfDayTemperatureEstimate]:
    """Estimate temperature (and its pace impact) at a few representative
    hours today, without a forecast API call -- see app/diurnal_temperature.py.
    The climatological curve is anchored to today's real reading via
    `anomaly` (actual minus climatological-now, computed once in
    _build_response): whatever gap exists between "what the curve says it
    should be right now" and "what it actually is right now" gets carried
    across the whole day, so an anomalously hot or cold day still shows up
    in the morning/evening estimates instead of pure climatology
    pretending today is a typical day.

    Each slot's speed_loss_pct compares that slot's *predicted* temperature
    against `reference_c` -- the SAME fixed reference used everywhere else
    in this module (see _REFERENCE_RUN_HOUR), not that slot's own normal.
    Comparing each hour to its own normal would make every slot read as
    "0% unusual" on an ordinary day regardless of hour, which defeats the
    purpose of showing three different slots at all: a runner comparing
    morning/midday/evening needs to see that midday is genuinely hotter
    than the evening the pace assumes, not just whether today is typical
    for whichever hour they're looking at.
    """
    estimates = []
    for label, hour in _TIME_OF_DAY_HOURS:
        estimated_temp, relative_pct = _predicted_temperature_and_pct(
            hour, normal, sunrise_hour, sunset_hour, anomaly, reference_c, sex
        )
        estimates.append(
            TimeOfDayTemperatureEstimate(
                label=label,  # type: ignore[arg-type]
                hour=int(hour),
                temperature_c=round(estimated_temp, 1),
                speed_loss_pct=relative_pct,
            )
        )
    return estimates


def _segment_estimates(
    normal: MonthNormal,
    sunrise_hour: float,
    sunset_hour: float,
    current_hour: float,
    anomaly: float,
    sex: str | None,
    reference_c: float,
    offsets_min: list[float],
) -> list[SegmentTemperatureEstimate]:
    """Same math as _time_of_day_estimates, but at caller-supplied minutes-
    from-now offsets instead of the three fixed slots -- e.g. one offset per
    block of a multi-segment workout, computed from how far into the
    session that block is expected to start (see paceCalc.ts on the
    frontend for how offsets are derived from segment durations). "Now" is
    the only start-time input this has: there's no scheduled-start-time
    field on an assignment today, so this necessarily assumes the workout
    starts at the moment the client asks."""
    estimates = []
    for offset_min in offsets_min:
        hour = current_hour + offset_min / 60.0
        estimated_temp, relative_pct = _predicted_temperature_and_pct(
            hour, normal, sunrise_hour, sunset_hour, anomaly, reference_c, sex
        )
        estimates.append(
            SegmentTemperatureEstimate(
                offset_min=offset_min,
                temperature_c=round(estimated_temp, 1),
                speed_loss_pct=relative_pct,
            )
        )
    return estimates


def _build_response(
    state: str,
    city: str,
    sex: str | None,
    temperature_c: float,
    humidity_pct: float,
    observed_at: datetime,
    sunrise_utc: datetime | None,
    sunset_utc: datetime | None,
    utc_offset_seconds: int | None,
    now: datetime,
    segment_offsets_min: list[float],
) -> WeatherResponse:
    unadjusted_pct = speed_loss_pct(temperature_c, sex)

    # Local date at the city, not the server's, decides which month's
    # normal applies -- only matters in the last few hours of a month, but
    # costs nothing to get right.
    local_now = now + timedelta(seconds=utc_offset_seconds) if utc_offset_seconds is not None else now
    normal = get_climate_normal(city, local_now.month)

    adjusted_pct = unadjusted_pct
    relative_to_normal_pct = unadjusted_pct
    reference_c: float | None = None
    time_of_day: list[TimeOfDayTemperatureEstimate] = []
    segments: list[SegmentTemperatureEstimate] = []
    if normal is not None:
        # Default to the flat monthly mean when sun-time data isn't
        # available yet (e.g. a cache row written before sun times were
        # tracked); prefer the climatological normal for the assumed
        # reference run hour whenever possible -- see _REFERENCE_RUN_HOUR
        # and speed_loss_pct_relative_to_normal's docstring for why a flat
        # mean misrepresents both an ordinary evening and an ordinary
        # midday.
        reference_c = normal.mean_c
        sunrise_hour = sunset_hour = current_hour = None
        if sunrise_utc is not None and sunset_utc is not None and utc_offset_seconds is not None:
            sunrise_hour = unix_timestamp_to_local_hour(int(sunrise_utc.timestamp()), utc_offset_seconds)
            sunset_hour = unix_timestamp_to_local_hour(int(sunset_utc.timestamp()), utc_offset_seconds)
            current_hour = unix_timestamp_to_local_hour(int(now.timestamp()), utc_offset_seconds)
            reference_c = estimate_temperature_at_hour(
                _REFERENCE_RUN_HOUR, sunrise_hour, sunset_hour, normal.low_c, normal.high_c
            )

        adjusted_pct = round(unadjusted_pct * acclimatization_multiplier(temperature_c, reference_c), 2)
        relative_to_normal_pct = speed_loss_pct_relative_to_normal(temperature_c, reference_c, sex)

        if sunrise_hour is not None and sunset_hour is not None and current_hour is not None:
            climatological_now = estimate_temperature_at_hour(
                current_hour, sunrise_hour, sunset_hour, normal.low_c, normal.high_c
            )
            anomaly = temperature_c - climatological_now
            time_of_day = _time_of_day_estimates(normal, sunrise_hour, sunset_hour, anomaly, sex, reference_c)
            if segment_offsets_min:
                segments = _segment_estimates(
                    normal, sunrise_hour, sunset_hour, current_hour, anomaly, sex, reference_c, segment_offsets_min
                )

    return WeatherResponse(
        state=state,
        city=city,
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        observed_at=observed_at,
        speed_loss_pct=adjusted_pct,
        speed_loss_pct_unadjusted=unadjusted_pct,
        speed_loss_pct_relative_to_normal=relative_to_normal_pct,
        climate_normal_temperature_c=normal.mean_c if normal else None,
        climate_normal_reference_c=reference_c,
        time_of_day_estimates=time_of_day,
        segment_estimates=segments,
    )


# A workout has at most a handful of segments -- this is just a sanity
# ceiling against a misbehaving client, not a real limit anyone should hit.
_MAX_SEGMENT_OFFSETS = 20


@router.get("/weather", response_model=WeatherResponse)
def get_weather(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    segment_offsets_min: list[float] = Query(default=[]),
) -> WeatherResponse:
    # Silently drop invalid/excess offsets rather than 422ing the whole
    # weather lookup over an optional, additive parameter -- a client
    # sending a slightly-off offset shouldn't lose the base weather data.
    offsets = [o for o in segment_offsets_min if o >= 0][:_MAX_SEGMENT_OFFSETS]

    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        profile = tx.execute(_SELECT_PROFILE, {"user_id": actor_id_raw}).first()
        city = profile.city if profile else None
        sex = profile.sex if profile else None
        if not city:
            return _empty_response("UNAVAILABLE", None)

        cache_row = tx.execute(_SELECT_CACHE, {"city": city}).first()
        now = datetime.now(timezone.utc)

        if cache_row is not None and now - cache_row.fetched_at < _CACHED_WINDOW:
            return _build_response(
                "CACHED",
                city,
                sex,
                float(cache_row.temperature_c),
                float(cache_row.humidity_pct),
                cache_row.provider_observed_at,
                cache_row.sunrise_utc,
                cache_row.sunset_utc,
                cache_row.utc_offset_seconds,
                now,
                offsets,
            )

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
                    "sunrise_utc": live.sunrise,
                    "sunset_utc": live.sunset,
                    "utc_offset_seconds": live.utc_offset_seconds,
                },
            )
            return _build_response(
                "LIVE",
                city,
                sex,
                live.temperature_c,
                live.humidity_pct,
                live.observed_at,
                live.sunrise,
                live.sunset,
                live.utc_offset_seconds,
                now,
                offsets,
            )

        if cache_row is not None and now - cache_row.fetched_at < _STALE_WINDOW:
            return _build_response(
                "STALE",
                city,
                sex,
                float(cache_row.temperature_c),
                float(cache_row.humidity_pct),
                cache_row.provider_observed_at,
                cache_row.sunrise_utc,
                cache_row.sunset_utc,
                cache_row.utc_offset_seconds,
                now,
                offsets,
            )

        return _empty_response("UNAVAILABLE", city)

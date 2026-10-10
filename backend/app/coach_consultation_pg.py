"""Postgres adapters for Coach Consultation.

These are the only place the consultation touches SQL. They are bound to an
already-actor-scoped transaction, so row-level security applies exactly as it
does everywhere else -- the adapter never widens what the Actor may read.

The queries are the ones the conversation handlers previously ran inline, kept
verbatim so adopting the module changes no answer the Athlete would see.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type, datetime, timedelta, timezone

from sqlalchemy import Connection, text

from app.coach_consultation import (
    LatestSelfReport,
    RecentActivitySummary,
    RecentTrainingSummary,
)
from app.evidence_retriever import EvidenceQuery
from app.evidence_repository import PostgresEvidenceRepository
from app.evidence_retriever import GraphEvidenceRetriever
from app.injury_guidance import EvidencePassage
from app.plan_scenario import AthleteFacts
from app.weather_client import fetch_live_weather

_SELECT_TODAYS_LOAD = text(
    "SELECT load_ratio, data_quality, acute_load, chronic_load, observation_days "
    "FROM training_load_daily "
    "WHERE athlete_id = :athlete_id AND date = :local_date AND unit = 'AU'"
)

_SELECT_LATEST_SELF_REPORT = text(
    """
    SELECT local_training_date, has_issue, severity_band, body_part
      FROM injury_reports
     WHERE athlete_id = :athlete_id
     ORDER BY local_training_date DESC
     LIMIT 1
    """
)

_SELECT_PROFILE_WEATHER = text(
    "SELECT p.city, w.temperature_c, w.humidity_pct, w.fetched_at "
    "FROM athlete_profiles p LEFT JOIN weather_cache w ON w.city = p.city "
    "WHERE p.user_id = :athlete_id"
)

_UPSERT_WEATHER_CACHE = text(
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

_SELECT_RECENT_ACTIVITIES = text(
    """
    SELECT local_training_date, distance_km, duration_minutes, rpe, device_metrics
      FROM completed_activities
     WHERE athlete_id = :athlete_id
       AND deleted_at IS NULL
       AND local_training_date BETWEEN :from_date AND :through_date
     ORDER BY performed_at DESC, id DESC
    """
)


class PostgresConsultationFactsReader:
    def __init__(self, tx: Connection, local_date: date_type) -> None:
        self._tx = tx
        self._local_date = local_date

    def read_athlete_facts(
        self, actor_id: str, local_date: date_type | None = None
    ) -> AthleteFacts:
        athlete_id = uuid.UUID(str(actor_id))
        on_date = local_date or self._local_date

        load = self._tx.execute(
            _SELECT_TODAYS_LOAD, {"athlete_id": athlete_id, "local_date": on_date}
        ).first()
        weather = self._tx.execute(
            _SELECT_PROFILE_WEATHER, {"athlete_id": athlete_id}
        ).first()

        city = weather.city if weather is not None else None
        temperature_c = (
            float(weather.temperature_c)
            if weather is not None and weather.temperature_c is not None
            else None
        )
        humidity_pct = (
            float(weather.humidity_pct)
            if weather is not None and weather.humidity_pct is not None
            else None
        )
        weather_state = (
            "CACHED" if weather is not None and weather.fetched_at else "UNAVAILABLE"
        )

        # Ensure real-time weather is fetched if cache is missing or stale (>10 min)
        if city:
            now = datetime.now(timezone.utc)
            is_stale = (
                weather is None
                or weather.fetched_at is None
                or (now - weather.fetched_at) > timedelta(minutes=10)
            )
            if is_stale:
                live = fetch_live_weather(city)
                if live is not None:
                    temperature_c = live.temperature_c
                    humidity_pct = live.humidity_pct
                    weather_state = "LIVE"
                    try:
                        self._tx.execute(
                            _UPSERT_WEATHER_CACHE,
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
                    except Exception:
                        pass

        return AthleteFacts(
            local_date=on_date,
            observation_days=(
                int(load.observation_days)
                if load is not None and load.observation_days is not None
                else 0
            ),
            acute_load=(
                float(load.acute_load)
                if load is not None and load.acute_load is not None
                else None
            ),
            chronic_load=(
                float(load.chronic_load)
                if load is not None and load.chronic_load is not None
                else None
            ),
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            weather_state=weather_state,
            city=city,
        )

    def read_recent_training_summary(
        self, actor_id: str, local_date: date_type | None = None
    ) -> RecentTrainingSummary:
        athlete_id = uuid.UUID(str(actor_id))
        through_date = local_date or self._local_date
        rows = self._tx.execute(
            _SELECT_RECENT_ACTIVITIES,
            {
                "athlete_id": athlete_id,
                "from_date": through_date - timedelta(days=27),
                "through_date": through_date,
            },
        ).all()

        def _metric(row, key: str) -> float | None:
            raw = dict(row.device_metrics or {}).get(key)
            try:
                return float(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None

        heart_rates = [v for row in rows if (v := _metric(row, "avgHeartRate")) is not None]
        cadences = [
            v for row in rows if (v := _metric(row, "avgCadenceStepsPerMin")) is not None
        ]
        recent = tuple(
            RecentActivitySummary(
                local_training_date=row.local_training_date,
                distance_km=float(row.distance_km) if row.distance_km is not None else None,
                duration_minutes=float(row.duration_minutes),
                average_heart_rate_bpm=(
                    round(value) if (value := _metric(row, "avgHeartRate")) is not None else None
                ),
                average_cadence_spm=(
                    round(value)
                    if (value := _metric(row, "avgCadenceStepsPerMin")) is not None
                    else None
                ),
                rpe=int(row.rpe) if row.rpe is not None else None,
            )
            for row in rows[:3]
        )
        return RecentTrainingSummary(
            window_days=28,
            activity_count=len(rows),
            total_distance_km=round(
                sum(float(row.distance_km or 0) for row in rows), 1
            ),
            total_duration_minutes=round(
                sum(float(row.duration_minutes) for row in rows), 1
            ),
            average_heart_rate_bpm=round(sum(heart_rates) / len(heart_rates))
            if heart_rates
            else None,
            average_cadence_spm=round(sum(cadences) / len(cadences)) if cadences else None,
            recent_activities=recent,
        )


class PostgresSelfReportReader:
    def __init__(self, tx: Connection) -> None:
        self._tx = tx

    def read_latest_self_report(self, actor_id: str) -> LatestSelfReport | None:
        row = self._tx.execute(
            _SELECT_LATEST_SELF_REPORT, {"athlete_id": uuid.UUID(str(actor_id))}
        ).first()
        if row is None:
            return None
        return LatestSelfReport(
            local_training_date=row.local_training_date,
            has_issue=bool(row.has_issue),
            severity_band=row.severity_band,
            body_part=row.body_part,
        )


class GraphEvidenceReader:
    """Loads the reviewed corpus for this transaction and retrieves from it."""

    def __init__(self, tx: Connection, corpus_version: str = "sports-medicine-v1") -> None:
        graph = PostgresEvidenceRepository(tx).load_graph(corpus_version)
        self._retriever = GraphEvidenceRetriever(graph)

    def retrieve(
        self, query: EvidenceQuery, *, limit: int = 5
    ) -> tuple[EvidencePassage, ...]:
        return self._retriever.retrieve(query, limit=limit)

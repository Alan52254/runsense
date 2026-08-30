"""Postgres adapters for Coach Consultation.

These are the only place the consultation touches SQL. They are bound to an
already-actor-scoped transaction, so row-level security applies exactly as it
does everywhere else -- the adapter never widens what the Actor may read.

The queries are the ones the conversation handlers previously ran inline, kept
verbatim so adopting the module changes no answer the Athlete would see.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import Connection, text

from app.coach_consultation import EvidenceQuery, LatestSelfReport
from app.evidence_repository import PostgresEvidenceRepository
from app.evidence_retriever import GraphEvidenceRetriever
from app.injury_guidance import EvidencePassage
from app.plan_scenario import AthleteFacts

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
            temperature_c=(
                float(weather.temperature_c)
                if weather is not None and weather.temperature_c is not None
                else None
            ),
            humidity_pct=(
                float(weather.humidity_pct)
                if weather is not None and weather.humidity_pct is not None
                else None
            ),
            weather_state="CACHED" if weather is not None and weather.fetched_at else "UNAVAILABLE",
            city=weather.city if weather is not None else None,
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
    """Adapts the reviewed-evidence retriever to the consultation's query type.

    The retriever still scores over text today; expressing the request as a
    query object is what lets that be replaced without touching any caller.
    """

    def __init__(self, tx: Connection, corpus_version: str = "sports-medicine-v1") -> None:
        graph = PostgresEvidenceRepository(tx).load_graph(corpus_version)
        self._retriever = GraphEvidenceRetriever(graph)

    def retrieve(
        self, query: EvidenceQuery, *, limit: int = 5
    ) -> tuple[EvidencePassage, ...]:
        terms = [query.free_text, query.body_part, query.topic, query.phase]
        return self._retriever.retrieve(
            " ".join(term for term in terms if term), limit=limit
        )

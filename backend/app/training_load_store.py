"""PostgreSQL orchestration for bounded Training Load Trend materialization."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Connection, text

from app.training_load import DailyLoadInput, calculate_training_load_series

_SELECT_CANONICAL_INPUTS = text(
    """
    SELECT 'activity' AS kind, id::text AS activity_id,
           local_training_date AS input_date, performed_at, session_load,
           unit, source_metric
      FROM completed_activities
     WHERE athlete_id = :athlete_id
       AND local_training_date BETWEEN :input_start AND :affected_end
    UNION ALL
    SELECT 'rest' AS kind, NULL AS activity_id,
           date AS input_date, NULL AS performed_at, NULL AS session_load,
           NULL AS unit, NULL AS source_metric
      FROM athlete_rest_days
     WHERE athlete_id = :athlete_id
       AND date BETWEEN :input_start AND :affected_end
    ORDER BY input_date, kind, activity_id
    """
)

_DELETE_AFFECTED = text(
    """
    DELETE FROM training_load_daily
     WHERE athlete_id = :athlete_id
       AND date BETWEEN :changed_date AND :affected_end
    """
)

_INSERT_POINT = text(
    """
    INSERT INTO training_load_daily (
        athlete_id, date, unit, session_load, source_metric,
        acute_load, chronic_load, load_ratio, data_quality,
        observation_days, algorithm_version, schema_version,
        computed_at, input_snapshot_hash
    ) VALUES (
        :athlete_id, :date, :unit, :session_load, :source_metric,
        :acute_load, :chronic_load, :load_ratio, :data_quality,
        :observation_days, :algorithm_version, :schema_version,
        :computed_at, :input_snapshot_hash
    )
    """
)

_LOCK_ATHLETE_TRAINING_LOAD = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"
)


def lock_athlete_training_load(conn: Connection, athlete_id: uuid.UUID) -> None:
    """Serialize every canonical load mutation for one Athlete.

    Different input dates can affect overlapping 28-day projection windows, so
    date-level locking is insufficient: all of an Athlete's canonical load
    mutations share this transaction lock.
    """

    conn.execute(
        _LOCK_ATHLETE_TRAINING_LOAD,
        {"lock_key": f"training-load:{athlete_id}"},
    )


def recompute_training_load(
    conn: Connection,
    athlete_id: uuid.UUID,
    changed_date: date,
) -> None:
    """Replace only the materialized dates affected by an input on D.

    The caller owns the actor-scoped transaction. The function performs one
    canonical-input read spanning D-27 through D+27 and writes D through D+27.
    """

    # Keep direct callers (including the admin backfill and on-demand reads)
    # safe as well as HTTP mutation callers. PostgreSQL advisory transaction
    # locks are re-entrant, so routes may acquire this before their canonical
    # write to protect cross-table invariants and call us in the same tx.
    lock_athlete_training_load(conn, athlete_id)
    affected_end = changed_date + timedelta(days=27)
    input_start = changed_date - timedelta(days=27)
    rows = conn.execute(
        _SELECT_CANONICAL_INPUTS,
        {
            "athlete_id": athlete_id,
            "input_start": input_start,
            "affected_end": affected_end,
        },
    ).all()
    inputs = [
        DailyLoadInput(
            activity_id=row.activity_id,
            local_training_date=row.input_date,
            performed_at=row.performed_at,
            session_load=Decimal(row.session_load),
            unit=row.unit,
            source_metric=row.source_metric,
        )
        for row in rows
        if row.kind == "activity"
    ]
    rests = {row.input_date for row in rows if row.kind == "rest"}
    units = {item.unit for item in inputs} | {"AU"}
    points = calculate_training_load_series(
        daily_inputs=inputs,
        confirmed_rest_dates=rests,
        end_date=affected_end,
        units=units,
    )
    computed_at = datetime.now(timezone.utc)

    conn.execute(
        _DELETE_AFFECTED,
        {
            "athlete_id": athlete_id,
            "changed_date": changed_date,
            "affected_end": affected_end,
        },
    )
    conn.execute(
        _INSERT_POINT,
        [
            {
                "athlete_id": athlete_id,
                "date": point.date,
                "unit": point.unit,
                "session_load": point.session_load,
                "source_metric": point.source_metric,
                "acute_load": point.acute_load,
                "chronic_load": point.chronic_load,
                "load_ratio": point.load_ratio,
                "data_quality": point.data_quality,
                "observation_days": point.observation_days,
                "algorithm_version": point.algorithm_version,
                "schema_version": point.schema_version,
                "computed_at": computed_at,
                "input_snapshot_hash": point.input_snapshot_hash,
            }
            for point in points
        ],
    )

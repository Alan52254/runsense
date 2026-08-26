from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app.clock import Clock, SystemClock
from app.db import actor_transaction, get_connection
from app.errors import ProfileTimezoneNotSetError, RestDayConflictsWithActivityError
from app.providers import CurrentActorProvider, ProfileTimezoneProvider
from app.routes.activities import (
    get_current_actor_provider,
    get_profile_timezone_provider,
)
from app.schemas import (
    RestDayRequest,
    RestDayResponse,
    TrainingLoadPointResponse,
    TrainingLoadSeriesResponse,
    TrainingLoadTrendResponse,
)
from app.training_load_store import lock_athlete_training_load, recompute_training_load

router = APIRouter()
_system_clock = SystemClock()


def get_clock() -> Clock:
    return _system_clock


_HAS_ACTIVITY = text(
    "SELECT EXISTS (SELECT 1 FROM completed_activities "
    "WHERE athlete_id=:athlete_id AND local_training_date=:date AND deleted_at IS NULL)"
)
_UPSERT_REST = text(
    "INSERT INTO athlete_rest_days (athlete_id,date) VALUES (:athlete_id,:date) "
    "ON CONFLICT (athlete_id,date) DO NOTHING RETURNING date"
)
_DELETE_REST = text(
    "DELETE FROM athlete_rest_days WHERE athlete_id=:athlete_id AND date=:date RETURNING date"
)
_EXPECTED_UNITS = text(
    "SELECT DISTINCT unit FROM completed_activities WHERE athlete_id=:athlete_id "
    "AND deleted_at IS NULL AND local_training_date BETWEEN :input_start AND :end_date"
)
_EXISTING_COUNTS = text(
    "SELECT unit,count(*) AS point_count FROM training_load_daily "
    "WHERE athlete_id=:athlete_id AND date BETWEEN :start_date AND :end_date "
    "GROUP BY unit"
)
_SELECT_TREND = text(
    "SELECT date,unit,source_metric,session_load,acute_load,chronic_load,load_ratio,"
    "data_quality,observation_days,algorithm_version,schema_version,computed_at,"
    "input_snapshot_hash FROM training_load_daily "
    "WHERE athlete_id=:athlete_id AND date BETWEEN :start_date AND :end_date "
    "ORDER BY CASE WHEN unit='AU' THEN 0 ELSE 1 END,unit,date"
)


@router.put("/rest-days/{training_date}", response_model=RestDayResponse)
def set_rest_day(
    training_date: date,
    payload: RestDayRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> RestDayResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        lock_athlete_training_load(tx, actor_id)
        changed = False
        if payload.confirmed:
            if tx.execute(
                _HAS_ACTIVITY, {"athlete_id": actor_id, "date": training_date}
            ).scalar_one():
                raise RestDayConflictsWithActivityError()
            changed = (
                tx.execute(
                    _UPSERT_REST,
                    {"athlete_id": actor_id, "date": training_date},
                ).first()
                is not None
            )
        else:
            changed = (
                tx.execute(
                    _DELETE_REST,
                    {"athlete_id": actor_id, "date": training_date},
                ).first()
                is not None
            )
        if changed:
            recompute_training_load(tx, actor_id, training_date)
    return RestDayResponse(date=training_date, confirmed=payload.confirmed)


@router.get("/training-load/trend", response_model=TrainingLoadTrendResponse)
def get_training_load_trend(
    end_date: date | None = None,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
    clock: Clock = Depends(get_clock),
) -> TrainingLoadTrendResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        resolved_end = end_date
        if resolved_end is None:
            timezone_name = timezone_provider.get_profile_timezone(str(actor_id))
            if not timezone_name:
                raise ProfileTimezoneNotSetError()
            try:
                resolved_end = clock.now_utc().astimezone(ZoneInfo(timezone_name)).date()
            except ZoneInfoNotFoundError as exc:
                raise ProfileTimezoneNotSetError() from exc

        start_date = resolved_end - timedelta(days=27)
        expected_units = {"AU"} | set(
            tx.execute(
                _EXPECTED_UNITS,
                {
                    "athlete_id": actor_id,
                    "input_start": start_date - timedelta(days=27),
                    "end_date": resolved_end,
                },
            ).scalars()
        )
        counts = {
            row.unit: row.point_count
            for row in tx.execute(
                _EXISTING_COUNTS,
                {
                    "athlete_id": actor_id,
                    "start_date": start_date,
                    "end_date": resolved_end,
                },
            )
        }
        if any(counts.get(unit) != 28 for unit in expected_units):
            recompute_training_load(tx, actor_id, start_date)

        rows = tx.execute(
            _SELECT_TREND,
            {
                "athlete_id": actor_id,
                "start_date": start_date,
                "end_date": resolved_end,
            },
        ).all()

    grouped = defaultdict(list)
    source_metrics: dict[str, str] = {}
    for row in rows:
        source_metrics[row.unit] = row.source_metric
        grouped[row.unit].append(
            TrainingLoadPointResponse(
                date=row.date,
                session_load=float(row.session_load),
                acute_load=float(row.acute_load),
                chronic_load=float(row.chronic_load),
                load_ratio=float(row.load_ratio) if row.load_ratio is not None else None,
                data_quality=row.data_quality,
                observation_days=row.observation_days,
                algorithm_version=row.algorithm_version,
                schema_version=row.schema_version,
                computed_at=row.computed_at,
                input_snapshot_hash=row.input_snapshot_hash,
            )
        )
    ordered_units = sorted(grouped, key=lambda value: (value != "AU", value))
    return TrainingLoadTrendResponse(
        start_date=start_date,
        end_date=resolved_end,
        series=[
            TrainingLoadSeriesResponse(
                unit=unit,
                source_metric=source_metrics[unit],
                points=grouped[unit],
            )
            for unit in ordered_units
        ],
    )

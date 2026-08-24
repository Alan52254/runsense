from __future__ import annotations

import os
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy import Connection, text

from app.activity_history_cursor import (
    InvalidActivityHistoryCursor,
    decode_activity_history_cursor,
    encode_activity_history_cursor,
)
from app.db import actor_transaction, get_connection
from app.errors import (
    AuthorizationError,
    IdempotencyKeyReusedWithDifferentPayloadError,
    ProfileTimezoneNotSetError,
)
from app.fingerprint import compute_request_fingerprint
from app.providers import (
    CurrentActorProvider,
    DbProfileTimezoneProvider,
    DemoCurrentActorProvider,
    NotImplementedCurrentActorProvider,
    NotImplementedProfileTimezoneProvider,
    ProfileTimezoneProvider,
)
from app.schemas import ActivityHistoryResponse, ActivityResponse, CreateActivityRequest
from app.training_load_store import lock_athlete_training_load, recompute_training_load

router = APIRouter()

_competition_demo_only = os.environ.get("COMPETITION_DEMO_ONLY", "").lower() == "true"

# Production default: fails loudly (see providers.py) rather than silently
# granting access. Override via app.dependency_overrides in tests, and
# eventually via real implementations from the Auth/Profile changes.
_default_actor_provider = NotImplementedCurrentActorProvider()
_default_timezone_provider = NotImplementedProfileTimezoneProvider()


def get_current_actor_provider(
    request: Request,
    conn: Connection = Depends(get_connection),
) -> CurrentActorProvider:
    if _competition_demo_only:
        return DemoCurrentActorProvider(request, conn)
    return _default_actor_provider


def get_profile_timezone_provider(
    conn: Connection = Depends(get_connection),
) -> ProfileTimezoneProvider:
    if _competition_demo_only:
        return DbProfileTimezoneProvider(conn)
    return _default_timezone_provider


_INSERT_SQL = text(
    """
    INSERT INTO completed_activities (
        athlete_id, client_mutation_id, request_fingerprint,
        provider, provider_activity_id,
        duration_minutes, rpe, performed_at,
        timezone_snapshot, local_training_date,
        session_load, unit, source_metric
    ) VALUES (
        :athlete_id, :client_mutation_id, :request_fingerprint,
        'manual', NULL,
        :duration_minutes, :rpe, :performed_at,
        :timezone_snapshot, :local_training_date,
        :session_load, 'AU', 'SESSION_RPE'
    )
    ON CONFLICT (athlete_id, client_mutation_id) DO NOTHING
    RETURNING id, athlete_id, client_mutation_id, provider, provider_activity_id,
              duration_minutes, rpe, performed_at, timezone_snapshot,
              local_training_date, session_load, unit, source_metric,
              server_version, created_at
    """
)

_SELECT_EXISTING_SQL = text(
    """
    SELECT id, athlete_id, client_mutation_id, provider, provider_activity_id,
           duration_minutes, rpe, performed_at, timezone_snapshot,
           local_training_date, session_load, unit, source_metric,
           server_version, created_at, request_fingerprint
    FROM completed_activities
    WHERE athlete_id = :athlete_id AND client_mutation_id = :client_mutation_id
    """
)

_DELETE_REST_DAY_SQL = text(
    "DELETE FROM athlete_rest_days WHERE athlete_id=:athlete_id AND date=:date"
)

_SELECT_HISTORY_FIRST_PAGE_SQL = text(
    """
    SELECT id, athlete_id, client_mutation_id, provider, provider_activity_id,
           duration_minutes, rpe, performed_at, timezone_snapshot,
           local_training_date, session_load, unit, source_metric,
           server_version, created_at
    FROM completed_activities
    WHERE athlete_id = :athlete_id
    ORDER BY performed_at DESC, id DESC
    LIMIT :limit_plus_one
    """
)

_SELECT_HISTORY_AFTER_CURSOR_SQL = text(
    """
    SELECT id, athlete_id, client_mutation_id, provider, provider_activity_id,
           duration_minutes, rpe, performed_at, timezone_snapshot,
           local_training_date, session_load, unit, source_metric,
           server_version, created_at
    FROM completed_activities
    WHERE athlete_id = :athlete_id
      AND (performed_at, id) < (:cursor_performed_at, :cursor_id)
    ORDER BY performed_at DESC, id DESC
    LIMIT :limit_plus_one
    """
)


def _row_to_response(row) -> ActivityResponse:
    return ActivityResponse(
        id=row.id,
        athlete_id=row.athlete_id,
        client_mutation_id=row.client_mutation_id,
        provider=row.provider,
        provider_activity_id=row.provider_activity_id,
        duration_minutes=row.duration_minutes,
        rpe=row.rpe,
        performed_at=row.performed_at,
        timezone_snapshot=row.timezone_snapshot,
        local_training_date=row.local_training_date,
        session_load=row.session_load,
        unit=row.unit,
        source_metric=row.source_metric,
        server_version=row.server_version,
        created_at=row.created_at,
    )


def _invalid_cursor_error(cursor: str) -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("query", "cursor"),
                "msg": "Value error, invalid activity history cursor",
                "input": cursor,
            }
        ]
    )


@router.get("/activities", response_model=ActivityHistoryResponse)
def list_activities(
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    conn: Connection = Depends(get_connection),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> ActivityHistoryResponse:
    actor_id_raw = actor_provider.get_current_actor_id()

    decoded_cursor = None
    if cursor is not None:
        try:
            decoded_cursor = decode_activity_history_cursor(cursor)
        except InvalidActivityHistoryCursor as exc:
            raise _invalid_cursor_error(cursor) from exc

    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        params = {
            "athlete_id": actor_id,
            "limit_plus_one": limit + 1,
        }
        query = _SELECT_HISTORY_FIRST_PAGE_SQL
        if decoded_cursor is not None:
            query = _SELECT_HISTORY_AFTER_CURSOR_SQL
            params.update(
                {
                    "cursor_performed_at": decoded_cursor.performed_at,
                    "cursor_id": decoded_cursor.activity_id,
                }
            )
        rows = tx.execute(query, params).all()

    has_next_page = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_next_page:
        last_row = page_rows[-1]
        next_cursor = encode_activity_history_cursor(
            performed_at=last_row.performed_at,
            activity_id=last_row.id,
        )
    return ActivityHistoryResponse(
        items=[_row_to_response(row) for row in page_rows],
        next_cursor=next_cursor,
    )


@router.post("/activities", response_model=ActivityResponse, status_code=201)
def create_activity(
    payload: CreateActivityRequest,
    response: Response,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
) -> ActivityResponse:
    # athlete_id is always derived from the authenticated actor (REQ-RLS-006,
    # design.md Decision 1) -- never accepted from the request body.
    actor_id_raw = actor_provider.get_current_actor_id()

    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)  # already validated by actor_transaction

        timezone_name = timezone_provider.get_profile_timezone(str(actor_id))
        if not timezone_name:
            raise ProfileTimezoneNotSetError()
        try:
            tzinfo = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ProfileTimezoneNotSetError() from exc

        local_training_date = payload.performed_at.astimezone(tzinfo).date()
        session_load = payload.duration_minutes * payload.rpe
        request_fingerprint = compute_request_fingerprint(
            payload.duration_minutes, payload.rpe, payload.performed_at
        )
        lock_athlete_training_load(tx, actor_id)

        inserted = tx.execute(
            _INSERT_SQL,
            {
                "athlete_id": actor_id,
                "client_mutation_id": payload.client_mutation_id,
                "request_fingerprint": request_fingerprint,
                "duration_minutes": payload.duration_minutes,
                "rpe": payload.rpe,
                "performed_at": payload.performed_at,
                "timezone_snapshot": timezone_name,
                "local_training_date": local_training_date,
                "session_load": session_load,
            },
        ).first()

        if inserted is not None:
            tx.execute(
                _DELETE_REST_DAY_SQL,
                {"athlete_id": actor_id, "date": local_training_date},
            )
            recompute_training_load(tx, actor_id, local_training_date)
            response.status_code = 201
            return _row_to_response(inserted)

        existing = tx.execute(
            _SELECT_EXISTING_SQL,
            {"athlete_id": actor_id, "client_mutation_id": payload.client_mutation_id},
        ).first()

        if existing is None:
            # Concurrent transaction inserted then rolled back, or a race we
            # lost visibility into. Safe to surface as a generic conflict.
            raise HTTPException(status_code=409, detail={"error": "CREATE_CONFLICT_RETRY"})

        if existing.request_fingerprint == request_fingerprint:
            response.status_code = 200
            return _row_to_response(existing)

        raise IdempotencyKeyReusedWithDifferentPayloadError(
            existing_id=str(existing.id),
            client_mutation_id=str(payload.client_mutation_id),
        )

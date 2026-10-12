"""Uploading a run's .fit file, and which coach assignment a run completed.

POST /activities/fit-upload        the athlete uploads one recorded run
GET  /activities/{id}/assignment   the assignment it completed, and the ones it could have
PUT  /activities/{id}/assignment   the athlete corrects that (or clears it)

See app/activity_upload.py for the rules. The athlete is always the actor:
every row read or written here is their own (RLS).
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app import activity_upload
from app.db import actor_transaction, get_connection
from app.errors import ProfileTimezoneNotSetError
from app.providers import CurrentActorProvider, ProfileTimezoneProvider
from app.routes.activities import get_current_actor_provider, get_profile_timezone_provider

router = APIRouter(tags=["activity-upload"])


class FitUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_base64: str = Field(min_length=1)
    rpe: int = Field(ge=1, le=10)


class AssignmentLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assigned_workout_id: uuid.UUID | None


@router.post("/activities/fit-upload", status_code=201)
def upload_fit(
    payload: FitUploadRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
) -> dict:
    actor_id_raw = actor_provider.get_current_actor_id()
    try:
        data = base64.b64decode(payload.file_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"error": "FIT_UNREADABLE", "message": "檔案內容無法讀取"}) from exc
    with actor_transaction(conn, actor_id_raw) as tx:
        athlete_id = uuid.UUID(actor_id_raw)
        tz_name = timezone_provider.get_profile_timezone(str(athlete_id))
        if not tz_name:
            raise ProfileTimezoneNotSetError()
        try:
            return activity_upload.ingest_fit(tx, athlete_id, data, payload.rpe, tz_name)
        except activity_upload.UploadRejected as exc:
            status = 409 if exc.code == "ACTIVITY_ALREADY_EXISTS" else 413 if exc.code == "FIT_TOO_LARGE" else 422
            raise HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)}) from exc


def _assignment_dict(row) -> dict:
    return {"id": str(row.id), "title": row.title, "local_date": row.local_date.isoformat()}


def _own_activity_date(tx: Connection, activity_id: uuid.UUID, athlete_id: uuid.UUID) -> date:
    on = tx.execute(text("SELECT local_training_date FROM completed_activities "
                         "WHERE id = :id AND athlete_id = :a AND deleted_at IS NULL"),
                    {"id": activity_id, "a": athlete_id}).scalar_one_or_none()
    if on is None:
        raise HTTPException(status_code=404, detail={"error": "ACTIVITY_NOT_FOUND"})
    return on


@router.get("/activities/{activity_id}/assignment")
def get_assignment_link(
    activity_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        athlete_id = uuid.UUID(actor_id_raw)
        on = _own_activity_date(tx, activity_id, athlete_id)
        current = tx.execute(text(
            """SELECT w.id, w.title, w.local_date, c.linked_by FROM assignment_completions c
                 JOIN assigned_workouts w ON w.id = c.assigned_workout_id WHERE c.activity_id = :id"""),
            {"id": activity_id}).first()
        options = activity_upload.candidates(tx, athlete_id, on, activity_id)
    return {"activity_date": on.isoformat(),
            "current": None if current is None else {**_assignment_dict(current), "linked_by": current.linked_by},
            "candidates": [_assignment_dict(r) for r in options],
            "window_days": activity_upload.MATCH_WINDOW_DAYS}


@router.put("/activities/{activity_id}/assignment")
def set_assignment_link(
    activity_id: uuid.UUID,
    payload: AssignmentLinkRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict:
    """The athlete's correction: this run completed that assignment, or none."""
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        athlete_id = uuid.UUID(actor_id_raw)
        on = _own_activity_date(tx, activity_id, athlete_id)
        if payload.assigned_workout_id is not None:
            allowed = {r.id for r in activity_upload.candidates(tx, athlete_id, on, activity_id)}
            if payload.assigned_workout_id not in allowed:
                raise HTTPException(status_code=422, detail={"error": "ASSIGNMENT_NOT_AVAILABLE"})
        activity_upload.link(tx, athlete_id, activity_id, on, payload.assigned_workout_id, "athlete")
    return {"activity_id": str(activity_id), "assigned_workout_id":
            str(payload.assigned_workout_id) if payload.assigned_workout_id else None}

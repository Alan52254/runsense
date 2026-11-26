"""FastAPI routes for Garmin wellness streams and runtime `.fit` activity upload."""

from __future__ import annotations

import base64
from datetime import date
from email.parser import BytesParser
from email.policy import default as _EMAIL_POLICY
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import AuthorizationError
from app.fit_telemetry import FitParseError
from app.garmin_ingest import (
    get_latest_wellness,
    get_wellness_trend,
    ingest_fit_activity,
    upsert_wellness_rows,
)
from app.providers import (
    CurrentActorProvider,
    ProfileTimezoneProvider,
)
from app.routes.activities import get_current_actor_provider, get_profile_timezone_provider

router = APIRouter(prefix="/garmin", tags=["garmin"])


class WellnessImportPayload(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    uds: list[dict[str, Any]] = Field(default_factory=list)
    sleep: list[dict[str, Any]] = Field(default_factory=list)
    source: str = Field(default="garmin_gdpr", max_length=64)


class FitUploadJsonPayload(BaseModel):
    fit_base64: str = Field(min_length=4)
    rpe: int | None = Field(default=None, ge=1, le=10)
    timezone: str | None = None
    client_mutation_id: str | None = None
    activity_name: str | None = None


def _require_actor(actor_provider: CurrentActorProvider) -> tuple[str, uuid.UUID]:
    actor_id_raw = actor_provider.get_current_actor_id()
    if not actor_id_raw:
        raise AuthorizationError("missing actor context")
    try:
        return actor_id_raw, uuid.UUID(actor_id_raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AuthorizationError("malformed actor context") from exc


def _merge_wellness_payload(payload: WellnessImportPayload) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for row in payload.items:
        key = str(row.get("local_date") or row.get("calendarDate") or "")[:10]
        if not key:
            raise ValueError("missing local_date or calendarDate")
        by_date.setdefault(key, {}).update(row)
    for row in payload.uds:
        key = str(row.get("local_date") or row.get("calendarDate") or "")[:10]
        if not key:
            raise ValueError("missing calendarDate in UDS record")
        by_date.setdefault(key, {}).update(row)
    for row in payload.sleep:
        key = str(row.get("local_date") or row.get("calendarDate") or "")[:10]
        if not key:
            raise ValueError("missing calendarDate in sleep record")
        by_date.setdefault(key, {}).update(row)
    return list(by_date.values())


@router.get("/wellness/latest")
def read_latest_wellness(
    on_date: date | None = None,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor_raw, actor_id = _require_actor(actor_provider)
    with actor_transaction(conn, actor_raw) as tx:
        latest = get_latest_wellness(tx, actor_id, on_date=on_date)
    return {
        "available": latest is not None,
        "wellness": latest.to_dict() if latest is not None else None,
    }


@router.get("/wellness/trend")
def read_wellness_trend(
    days: int = Query(14, ge=1, le=90),
    on_date: date | None = None,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor_raw, actor_id = _require_actor(actor_provider)
    with actor_transaction(conn, actor_raw) as tx:
        trend = get_wellness_trend(tx, actor_id, on_date=on_date, days=days)
    return {
        "days": days,
        "items": [item.to_dict() for item in trend],
    }


@router.post("/wellness/import")
def import_wellness(
    payload: WellnessImportPayload,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor_raw, actor_id = _require_actor(actor_provider)
    try:
        rows = _merge_wellness_payload(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "INVALID_WELLNESS_PAYLOAD", "detail": str(exc)}
        ) from exc
    with actor_transaction(conn, actor_raw) as tx:
        try:
            imported = upsert_wellness_rows(tx, actor_id, rows, source=payload.source)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail={"error": "INVALID_WELLNESS_PAYLOAD", "detail": str(exc)}
            ) from exc
    return {"imported_days": imported, "source": payload.source}


async def _extract_multipart_fit(
    request: Request, raw_content_type: str
) -> tuple[bytes, int | None, str | None, str | None, str | None]:
    """Read FIT multipart payload using Starlette's parser or stdlib fallback."""
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(
                status_code=422,
                detail={"error": "INVALID_FIT_FILE", "detail": "missing file field"},
            )
        fit_bytes = await upload.read()
        raw_rpe = form.get("rpe")
        rpe = int(str(raw_rpe)) if raw_rpe is not None and str(raw_rpe).strip() else None
        tz_override = str(form.get("timezone")) if form.get("timezone") else None
        client_mutation_id = (
            str(form.get("client_mutation_id")) if form.get("client_mutation_id") else None
        )
        activity_name = str(form.get("activity_name")) if form.get("activity_name") else None
        return fit_bytes, rpe, tz_override, client_mutation_id, activity_name
    except (AssertionError, RuntimeError):
        raw_body = await request.body()
        envelope = (
            b"Content-Type: "
            + raw_content_type.encode("latin-1", errors="replace")
            + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + raw_body
        )
        msg = BytesParser(policy=_EMAIL_POLICY).parsebytes(envelope)
        if not msg.is_multipart():
            raise HTTPException(
                status_code=422,
                detail={"error": "INVALID_FIT_FILE", "detail": "malformed multipart payload"},
            )
        fields: dict[str, bytes] = {}
        for part in msg.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if field_name:
                payload_bytes = part.get_payload(decode=True)
                fields[str(field_name)] = payload_bytes if payload_bytes is not None else b""
        if "file" not in fields:
            raise HTTPException(
                status_code=422,
                detail={"error": "INVALID_FIT_FILE", "detail": "missing file field"},
            )
        fit_bytes = fields["file"]
        raw_rpe_txt = fields.get("rpe", b"").decode("utf-8", errors="replace").strip()
        rpe = int(raw_rpe_txt) if raw_rpe_txt else None
        tz_txt = fields.get("timezone", b"").decode("utf-8", errors="replace").strip()
        mut_txt = fields.get("client_mutation_id", b"").decode("utf-8", errors="replace").strip()
        name_txt = fields.get("activity_name", b"").decode("utf-8", errors="replace").strip()
        return (
            fit_bytes,
            rpe,
            tz_txt or None,
            mut_txt or None,
            name_txt or None,
        )


@router.post("/fit/upload")
async def upload_fit_activity(
    request: Request,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
) -> dict[str, Any]:
    actor_raw, actor_id = _require_actor(actor_provider)
    raw_content_type = request.headers.get("content-type") or ""
    content_type = raw_content_type.lower()

    rpe: int | None = None
    tz_override: str | None = None
    client_mutation_id: str | None = None
    activity_name: str | None = None

    if "multipart/form-data" in content_type:
        fit_bytes, rpe, tz_override, client_mutation_id, activity_name = (
            await _extract_multipart_fit(request, raw_content_type)
        )
    else:
        try:
            body = await request.json()
            parsed = FitUploadJsonPayload.model_validate(body)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "INVALID_FIT_FILE", "detail": str(exc)},
            ) from exc
        try:
            fit_bytes = base64.b64decode(parsed.fit_base64, validate=True)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "INVALID_FIT_FILE", "detail": "invalid base64 payload"},
            ) from exc
        rpe = parsed.rpe
        tz_override = parsed.timezone
        client_mutation_id = parsed.client_mutation_id
        activity_name = parsed.activity_name

    if not fit_bytes:
        raise HTTPException(
            status_code=422,
            detail={"error": "INVALID_FIT_FILE", "detail": "empty FIT payload"},
        )

    with actor_transaction(conn, actor_raw) as tx:
        profile_row = tx.execute(
            text("SELECT sex FROM athlete_profiles WHERE user_id = :u"),
            {"u": actor_id},
        ).first()
        sex = str(profile_row.sex) if profile_row and profile_row.sex else "male"
        tz_name = tz_override or timezone_provider.get_profile_timezone(actor_raw) or "Asia/Taipei"
        try:
            result = ingest_fit_activity(
                tx,
                actor_id,
                fit_bytes,
                rpe=rpe,
                timezone_name=tz_name,
                sex=sex,
                client_mutation_id=client_mutation_id,
                activity_name=activity_name,
            )
        except FitParseError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "INVALID_FIT_FILE", "detail": str(exc)},
            ) from exc

    return result

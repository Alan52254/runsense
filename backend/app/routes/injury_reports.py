from __future__ import annotations

import hashlib
import json
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import IdempotencyKeyReusedWithDifferentPayloadError, ProfileTimezoneNotSetError
from app.providers import CurrentActorProvider, ProfileTimezoneProvider
from app.routes.activities import get_current_actor_provider, get_profile_timezone_provider
from app.schemas import CreateInjuryReportRequest, InjuryReportListResponse, InjuryReportResponse

router = APIRouter(tags=["injury-reports"])

_REPORT_COLUMNS = """
    report.id, report.athlete_id, report.client_mutation_id,
    report.has_issue, report.severity_band, report.body_part,
    report.reported_at, report.timezone_snapshot, report.local_training_date,
    detail.free_text, report.created_at
"""

_INSERT_REPORT = text(
    """
    INSERT INTO injury_reports (
      athlete_id, client_mutation_id, request_fingerprint, has_issue,
      severity_band, body_part, reported_at, timezone_snapshot, local_training_date
    ) VALUES (
      :athlete_id, :client_mutation_id, :request_fingerprint, :has_issue,
      :severity_band, :body_part, :reported_at, :timezone_snapshot, :local_training_date
    )
    ON CONFLICT (athlete_id, client_mutation_id) DO NOTHING
    RETURNING id
    """
)

_SELECT_ONE = text(
    f"""
    SELECT {_REPORT_COLUMNS}, report.request_fingerprint
      FROM injury_reports report
      LEFT JOIN injury_report_details detail ON detail.injury_report_id = report.id
     WHERE report.athlete_id=:athlete_id AND report.client_mutation_id=:client_mutation_id
    """
)

_SELECT_HISTORY = text(
    f"""
    SELECT {_REPORT_COLUMNS}
      FROM injury_reports report
      LEFT JOIN injury_report_details detail ON detail.injury_report_id = report.id
     WHERE report.athlete_id=:athlete_id
     ORDER BY report.reported_at DESC, report.id DESC
    """
)


def _fingerprint(payload: CreateInjuryReportRequest) -> str:
    canonical = json.dumps(
        {
            "body_part": payload.body_part,
            "free_text": payload.free_text,
            "has_issue": payload.has_issue,
            "reported_at": payload.reported_at.isoformat().replace("+00:00", "Z"),
            "severity_band": payload.severity_band,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _response(row) -> InjuryReportResponse:
    return InjuryReportResponse(
        id=row.id,
        athlete_id=row.athlete_id,
        client_mutation_id=row.client_mutation_id,
        has_issue=row.has_issue,
        severity_band=row.severity_band,
        body_part=row.body_part,
        reported_at=row.reported_at,
        timezone_snapshot=row.timezone_snapshot,
        local_training_date=row.local_training_date,
        free_text=row.free_text,
        created_at=row.created_at,
    )


@router.post("/injury-reports", response_model=InjuryReportResponse, status_code=201)
def create_injury_report(
    payload: CreateInjuryReportRequest,
    response: Response,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
) -> InjuryReportResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        timezone_name = timezone_provider.get_profile_timezone(str(actor_id))
        if not timezone_name:
            raise ProfileTimezoneNotSetError()
        try:
            local_date = payload.reported_at.astimezone(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError as exc:
            raise ProfileTimezoneNotSetError() from exc

        request_fingerprint = _fingerprint(payload)
        inserted = tx.execute(
            _INSERT_REPORT,
            {
                "athlete_id": actor_id,
                "client_mutation_id": payload.client_mutation_id,
                "request_fingerprint": request_fingerprint,
                "has_issue": payload.has_issue,
                "severity_band": payload.severity_band,
                "body_part": payload.body_part,
                "reported_at": payload.reported_at,
                "timezone_snapshot": timezone_name,
                "local_training_date": local_date,
            },
        ).first()

        if inserted is not None:
            if payload.free_text is not None:
                tx.execute(
                    text(
                        "INSERT INTO injury_report_details (injury_report_id, free_text) "
                        "VALUES (:report_id, :free_text)"
                    ),
                    {"report_id": inserted.id, "free_text": payload.free_text},
                )
            row = tx.execute(
                _SELECT_ONE,
                {"athlete_id": actor_id, "client_mutation_id": payload.client_mutation_id},
            ).one()
            response.status_code = 201
            return _response(row)

        existing = tx.execute(
            _SELECT_ONE,
            {"athlete_id": actor_id, "client_mutation_id": payload.client_mutation_id},
        ).first()
        if existing is None:
            raise HTTPException(status_code=409, detail={"error": "CREATE_CONFLICT_RETRY"})
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyKeyReusedWithDifferentPayloadError(
                existing_id=str(existing.id),
                client_mutation_id=str(payload.client_mutation_id),
            )
        response.status_code = 200
        return _response(existing)


@router.get("/injury-reports", response_model=InjuryReportListResponse)
def list_injury_reports(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> InjuryReportListResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        rows = tx.execute(_SELECT_HISTORY, {"athlete_id": actor_id}).all()
        return InjuryReportListResponse(items=[_response(row) for row in rows])

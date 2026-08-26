"""Settings -- Security/Privacy/Integration.

docs/mvp-checklist.md pulled this back into scope from "Deferred past MVP".
Demo-appropriate scope, not full compliance infrastructure -- see
backend/README.md's Settings section for exactly what each endpoint does and
does not do (REQ-AUTH-007/008, REQ-PRIV-001..006, REQ-GARMIN-001,
REQ-AUDIT-001/002).

Settings use a distinct `/me/settings` prefix so the surface remains grouped by concern.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import AuthorizationError, InvalidMfaCodeError, SessionNotFoundError
from app.providers import (
    CurrentActorProvider,
    CurrentSessionProvider,
    DemoCurrentActorProvider,
    DemoCurrentSessionProvider,
    NoCurrentSessionProvider,
)
from app.routes.activities import _competition_demo_only, get_current_actor_provider
from app.schemas import (
    ActivityResponse,
    AuditLogEntryResponse,
    AuditLogListResponse,
    AuthSessionListResponse,
    AuthSessionResponse,
    DeletionRequestResponse,
    GarminIntegrationResponse,
    MfaVerifyRequest,
    MfaVerifyResponse,
    PrivacyExportResponse,
    ProfileResponse,
    TrainingLoadPointResponse,
)

router = APIRouter(prefix="/me/settings", tags=["settings"])

# Matches the fixed demo code documented in web/README.md ("The MFA and
# step-up challenges accept the fixed code 424242"). This is a lightweight
# MFA-satisfied toggle for demonstrating REQ-AUTH-007's gate on the UI, not
# a real TOTP/SMS provider integration.
_DEMO_MFA_CODE = "424242"

_default_session_provider = NoCurrentSessionProvider()


def get_current_session_provider(request: Request) -> CurrentSessionProvider:
    if _competition_demo_only:
        return DemoCurrentSessionProvider(request)
    return _default_session_provider


_SELECT_SESSIONS = text(
    """
    SELECT id, device, ip_masked, location, last_active_at
      FROM auth_sessions
     WHERE user_id = :actor_id AND revoked_at IS NULL
     ORDER BY last_active_at DESC
    """
)

_REVOKE_SESSION = text(
    """
    UPDATE auth_sessions SET revoked_at = now()
     WHERE id = :session_id AND user_id = :actor_id AND revoked_at IS NULL
    RETURNING id
    """
)

_MARK_MFA_SATISFIED = text(
    """
    UPDATE auth_sessions SET mfa_satisfied = true
     WHERE id = :session_id AND user_id = :actor_id
    RETURNING id
    """
)

_SELECT_PROFILE = text("SELECT city, timezone, sex FROM athlete_profiles WHERE user_id = :actor_id")

_SELECT_ALL_ACTIVITIES = text(
    """
    SELECT id, athlete_id, client_mutation_id, provider, provider_activity_id,
           duration_minutes, rpe, performed_at, timezone_snapshot,
           local_training_date, session_load, unit, source_metric,
           server_version, created_at, structure, distance_km, device_metrics
      FROM completed_activities
     WHERE athlete_id = :actor_id
     ORDER BY performed_at DESC, id DESC
    """
)

_SELECT_ALL_TRAINING_LOAD = text(
    """
    SELECT date, session_load, acute_load, chronic_load, load_ratio, data_quality,
           observation_days, algorithm_version, schema_version, computed_at,
           input_snapshot_hash
      FROM training_load_daily
     WHERE athlete_id = :actor_id AND unit = 'AU'
     ORDER BY date
    """
)

_INSERT_EXPORT_AUDIT = text(
    "INSERT INTO audit_log (actor_id, event, summary) "
    "VALUES (:actor_id, 'DATA_EXPORT', 'Athlete exported their own data via GET /me/settings/privacy/export')"
)

_SET_DELETION_REQUESTED = text(
    """
    UPDATE users SET deletion_requested_at = now()
     WHERE id = :actor_id
    RETURNING deletion_requested_at
    """
)

_SELECT_AUDIT_LOG = text(
    """
    SELECT id, event, summary, created_at
      FROM audit_log
     WHERE actor_id = :actor_id
     ORDER BY created_at DESC, id DESC
     LIMIT 200
    """
)


def require_demo_mfa(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    session_provider: CurrentSessionProvider = Depends(get_current_session_provider),
) -> None:
    """Require the current demo session's MFA flag for coach-only routes.

    Test and future non-demo providers may have no session concept; their
    authorization remains the responsibility of the injected actor provider.
    """

    if not _competition_demo_only or not isinstance(actor_provider, DemoCurrentActorProvider):
        return
    session_id = session_provider.get_current_session_id()
    if session_id is None:
        raise AuthorizationError("current demo token has no session")
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        satisfied = tx.execute(
            text(
                "SELECT 1 FROM auth_sessions "
                "WHERE id=:session_id AND user_id=:actor_id "
                "AND revoked_at IS NULL AND mfa_satisfied=true"
            ),
            {"session_id": uuid.UUID(session_id), "actor_id": uuid.UUID(actor_id_raw)},
        ).first()
    if satisfied is None:
        raise AuthorizationError("current session has not satisfied MFA")


@router.get("/sessions", response_model=AuthSessionListResponse)
def list_sessions(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    session_provider: CurrentSessionProvider = Depends(get_current_session_provider),
) -> AuthSessionListResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    current_session_id = session_provider.get_current_session_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        rows = tx.execute(_SELECT_SESSIONS, {"actor_id": uuid.UUID(actor_id_raw)}).all()
    return AuthSessionListResponse(
        items=[
            AuthSessionResponse(
                id=row.id,
                device=row.device,
                ip_masked=row.ip_masked,
                location=row.location,
                last_active_at=row.last_active_at,
                is_current=(current_session_id is not None and str(row.id) == current_session_id),
            )
            for row in rows
        ]
    )


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> None:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        row = tx.execute(
            _REVOKE_SESSION,
            {"session_id": session_id, "actor_id": uuid.UUID(actor_id_raw)},
        ).first()
    if row is None:
        # Revoking the current session is allowed for MVP (see this change's
        # brief) -- no special-casing there. Only "not this actor's session"
        # (or already revoked / never existed) is rejected.
        raise SessionNotFoundError()


@router.post("/mfa/verify", response_model=MfaVerifyResponse)
def verify_mfa(
    payload: MfaVerifyRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    session_provider: CurrentSessionProvider = Depends(get_current_session_provider),
) -> MfaVerifyResponse:
    if payload.code != _DEMO_MFA_CODE:
        raise InvalidMfaCodeError()

    actor_id_raw = actor_provider.get_current_actor_id()
    session_id = session_provider.get_current_session_id()
    if _competition_demo_only and isinstance(actor_provider, DemoCurrentActorProvider) and session_id is None:
        raise AuthorizationError("current demo token has no session")
    with actor_transaction(conn, actor_id_raw) as tx:
        if session_id is not None:
            tx.execute(
                _MARK_MFA_SATISFIED,
                {"session_id": uuid.UUID(session_id), "actor_id": uuid.UUID(actor_id_raw)},
            )
    return MfaVerifyResponse(mfa_satisfied=True)


@router.get("/privacy/export", response_model=PrivacyExportResponse)
def export_privacy_data(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> PrivacyExportResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        profile_row = tx.execute(_SELECT_PROFILE, {"actor_id": actor_id}).first()
        activity_rows = tx.execute(_SELECT_ALL_ACTIVITIES, {"actor_id": actor_id}).all()
        load_rows = tx.execute(_SELECT_ALL_TRAINING_LOAD, {"actor_id": actor_id}).all()
        tx.execute(_INSERT_EXPORT_AUDIT, {"actor_id": actor_id})

    return PrivacyExportResponse(
        exported_at=datetime.now(timezone.utc),
        profile=ProfileResponse(
            city=profile_row.city if profile_row is not None else None,
            timezone=profile_row.timezone if profile_row is not None else "",
            sex=profile_row.sex if profile_row is not None else None,
        ),
        completed_activities=[
            ActivityResponse(
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
                structure=row.structure,
                distance_km=row.distance_km,
                device_metrics=row.device_metrics,
            )
            for row in activity_rows
        ],
        training_load_daily=[
            TrainingLoadPointResponse(
                date=row.date,
                session_load=row.session_load,
                acute_load=row.acute_load,
                chronic_load=row.chronic_load,
                load_ratio=row.load_ratio,
                data_quality=row.data_quality,
                observation_days=row.observation_days,
                algorithm_version=row.algorithm_version,
                schema_version=row.schema_version,
                computed_at=row.computed_at,
                input_snapshot_hash=row.input_snapshot_hash,
            )
            for row in load_rows
        ],
    )


@router.post("/privacy/deletion-request", response_model=DeletionRequestResponse)
def request_deletion(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> DeletionRequestResponse:
    # Records the request only -- REQ-PRIV-003/005's actual retention-period
    # deletion pipeline is out of scope for this MVP (see this change's
    # brief). Nothing is deleted or scheduled here.
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        row = tx.execute(
            _SET_DELETION_REQUESTED, {"actor_id": uuid.UUID(actor_id_raw)}
        ).first()
    return DeletionRequestResponse(deletion_requested_at=row.deletion_requested_at)


@router.get("/integrations/garmin", response_model=GarminIntegrationResponse)
def get_garmin_integration_status(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> GarminIntegrationResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw):
        pass
    enabled = os.environ.get("GARMIN_ACTIVITY_SYNC_ENABLED", "").lower() == "true"
    return GarminIntegrationResponse(
        enabled=enabled,
        reason="GARMIN_ACTIVITY_SYNC_ENABLED is off (Phase 1A)"
        if not enabled
        else "GARMIN_ACTIVITY_SYNC_ENABLED is on",
    )


@router.get("/audit-log", response_model=AuditLogListResponse)
def list_audit_log(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> AuditLogListResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        rows = tx.execute(_SELECT_AUDIT_LOG, {"actor_id": uuid.UUID(actor_id_raw)}).all()
    return AuditLogListResponse(
        items=[
            AuditLogEntryResponse(
                id=row.id, event=row.event, created_at=row.created_at, summary=row.summary
            )
            for row in rows
        ]
    )

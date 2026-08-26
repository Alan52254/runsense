from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import AuthorizationError
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.schemas import (
    ConsentGrantListResponse,
    ConsentGrantResponse,
    ConsentScope,
    TeamMembershipListResponse,
    TeamMembershipResponse,
    UpdateConsentGrantRequest,
    UpdateTeamMembershipRequest,
)

router = APIRouter(prefix="/me", tags=["me"])

_SELECT_MEMBERSHIPS = text(
    """
    SELECT tm.team_id, t.name AS team_name,
           COALESCE(app_team_primary_coach_name(tm.team_id), '—') AS coach_name,
           tm.role, tm.status, tm.invited_at, tm.joined_at, tm.left_at
      FROM team_memberships tm
      JOIN teams t ON t.id = tm.team_id
     WHERE tm.user_id = :actor_id AND tm.role = 'athlete'
     ORDER BY CASE tm.status WHEN 'INVITED' THEN 1 WHEN 'ACTIVE' THEN 2 ELSE 3 END,
              t.name
    """
)

_SELECT_ONE_MEMBERSHIP = text(
    """
    SELECT tm.team_id, t.name AS team_name,
           COALESCE(app_team_primary_coach_name(tm.team_id), '—') AS coach_name,
           tm.role, tm.status, tm.invited_at, tm.joined_at, tm.left_at
      FROM team_memberships tm
      JOIN teams t ON t.id = tm.team_id
     WHERE tm.team_id = :team_id
       AND tm.user_id = :actor_id
       AND tm.role = 'athlete'
    """
)

_SELECT_CONSENTS = text(
    """
    SELECT team_id, scope, granted, changed_at
      FROM consent_grants
     WHERE athlete_id = :actor_id
     ORDER BY team_id, scope
    """
)

_INSERT_CONSENT_AUDIT = text(
    "INSERT INTO audit_log (actor_id, event, summary) "
    "VALUES (:actor_id, :event, :summary)"
)


def _membership_response(row) -> TeamMembershipResponse:
    return TeamMembershipResponse(
        team_id=row.team_id,
        team_name=row.team_name,
        coach_name=row.coach_name,
        role=row.role,
        status=row.status,
        invited_at=row.invited_at,
        joined_at=row.joined_at,
        left_at=row.left_at,
    )


@router.get("/team-memberships", response_model=TeamMembershipListResponse)
def list_my_team_memberships(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> TeamMembershipListResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        rows = tx.execute(_SELECT_MEMBERSHIPS, {"actor_id": actor_id}).all()
        return TeamMembershipListResponse(items=[_membership_response(row) for row in rows])


@router.patch("/team-memberships/{team_id}", response_model=TeamMembershipResponse)
def update_my_team_membership(
    team_id: uuid.UUID,
    payload: UpdateTeamMembershipRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> TeamMembershipResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        current = tx.execute(
            _SELECT_ONE_MEMBERSHIP, {"team_id": team_id, "actor_id": actor_id}
        ).first()
        if current is None:
            raise AuthorizationError("membership unavailable")

        expected = "INVITED" if payload.action in {"accept", "decline"} else "ACTIVE"
        if current.status != expected:
            raise AuthorizationError("invalid membership transition")

        if payload.action == "accept":
            tx.execute(
                text(
                    "UPDATE team_memberships SET status='ACTIVE', joined_at=now(), left_at=NULL "
                    "WHERE team_id=:team_id AND user_id=:actor_id AND role='athlete'"
                ),
                {"team_id": team_id, "actor_id": actor_id},
            )
        else:
            revoked_scopes = tx.execute(
                text(
                    "UPDATE consent_grants SET granted=false, changed_at=now() "
                    "WHERE team_id=:team_id AND athlete_id=:actor_id AND granted=true "
                    "RETURNING scope"
                ),
                {"team_id": team_id, "actor_id": actor_id},
            ).scalars().all()
            for revoked_scope in revoked_scopes:
                tx.execute(
                    _INSERT_CONSENT_AUDIT,
                    {
                        "actor_id": actor_id,
                        "event": "CONSENT_REVOKE",
                        "summary": f"Revoked {revoked_scope} while leaving team",
                    },
                )
            tx.execute(
                text(
                    "UPDATE team_memberships SET status='LEFT', left_at=now() "
                    "WHERE team_id=:team_id AND user_id=:actor_id AND role='athlete'"
                ),
                {"team_id": team_id, "actor_id": actor_id},
            )

        updated = tx.execute(
            _SELECT_ONE_MEMBERSHIP, {"team_id": team_id, "actor_id": actor_id}
        ).one()
        return _membership_response(updated)


@router.get("/consent-grants", response_model=ConsentGrantListResponse)
def list_my_consent_grants(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> ConsentGrantListResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        rows = tx.execute(_SELECT_CONSENTS, {"actor_id": actor_id}).all()
        return ConsentGrantListResponse(
            items=[
                ConsentGrantResponse(
                    team_id=row.team_id,
                    scope=row.scope,
                    granted=row.granted,
                    changed_at=row.changed_at,
                )
                for row in rows
            ]
        )


@router.patch("/consent-grants/{scope}", response_model=ConsentGrantResponse)
def update_my_consent_grant(
    scope: ConsentScope,
    payload: UpdateConsentGrantRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> ConsentGrantResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        active = tx.execute(
            text(
                "SELECT 1 FROM team_memberships WHERE team_id=:team_id "
                "AND user_id=:actor_id AND role='athlete' AND status='ACTIVE'"
            ),
            {"team_id": payload.team_id, "actor_id": actor_id},
        ).first()
        if active is None:
            raise AuthorizationError("active athlete membership required")

        row = tx.execute(
            text(
                """
                INSERT INTO consent_grants (team_id, athlete_id, scope, granted, changed_at)
                VALUES (:team_id, :actor_id, :scope, :granted, now())
                ON CONFLICT (team_id, athlete_id, scope)
                DO UPDATE SET granted=EXCLUDED.granted, changed_at=now()
                RETURNING team_id, scope, granted, changed_at
                """
            ),
            {
                "team_id": payload.team_id,
                "actor_id": actor_id,
                "scope": scope,
                "granted": payload.granted,
            },
        ).one()
        tx.execute(
            _INSERT_CONSENT_AUDIT,
            {
                "actor_id": actor_id,
                "event": "CONSENT_GRANT" if payload.granted else "CONSENT_REVOKE",
                "summary": f"{'Granted' if payload.granted else 'Revoked'} {scope} consent",
            },
        )
        return ConsentGrantResponse(
            team_id=row.team_id,
            scope=row.scope,
            granted=row.granted,
            changed_at=row.changed_at,
        )

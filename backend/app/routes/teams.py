"""Coach Team Overview + Coach Athlete Detail (docs/mvp-checklist.md Item 1).

See CONTEXT.md for Team / Team Role / Team Membership / Coach Roster Row /
Consent Scope. A Coach Roster Row is a query-time projection: it is never a
stored copy of athlete data, and a field is only populated when the
athlete's currently granted Consent Scopes cover it (REQ-DATAOWN-001-style
posture already used for completed_activities).

The verified Actor remains the transaction-local RLS context throughout the
request. Target Athlete ids are query values only. Database SELECT policies
independently verify active shared Team Membership, coach-like Team Role, and
the required current Consent Scope.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import TeamAthleteNotFoundError
from app.providers import CurrentActorProvider
from app.routes.activities import _row_to_response, get_current_actor_provider
from app.routes.settings import require_demo_mfa
from app.schemas import (
    ActivityHistoryResponse,
    CoachRosterRowResponse,
    MyTeamsResponse,
    TeamRosterResponse,
    TeamSummaryResponse,
)
from app.team_authorization import require_coach_role

router = APIRouter(prefix="/teams", tags=["teams"])

_SELECT_MY_TEAMS = text(
    """
    SELECT tm.team_id, t.name, tm.role
      FROM team_memberships tm
      JOIN teams t ON t.id = tm.team_id
     WHERE tm.user_id = :actor_id
       AND tm.role IN ('coach', 'head_coach', 'owner')
       AND tm.status = 'ACTIVE'
     ORDER BY t.name
    """
)

_SELECT_ACTIVE_ATHLETES = text(
    """
    SELECT tm.user_id AS athlete_id, tm.status, tm.joined_at,
           u.display_name, u.email
      FROM team_memberships tm
      JOIN users u ON u.id = tm.user_id
     WHERE tm.team_id = :team_id
       AND tm.role = 'athlete'
       AND tm.status = 'ACTIVE'
    """
)

_SELECT_ONE_ACTIVE_ATHLETE = text(
    """
    SELECT tm.user_id AS athlete_id, tm.status, tm.joined_at,
           u.display_name, u.email
      FROM team_memberships tm
      JOIN users u ON u.id = tm.user_id
     WHERE tm.team_id = :team_id
       AND tm.user_id = :athlete_id
       AND tm.role = 'athlete'
       AND tm.status = 'ACTIVE'
    """
)

_SELECT_CONSENTS = text(
    """
    SELECT athlete_id, scope FROM consent_grants
     WHERE team_id = :team_id AND granted = true
    """
)

_SELECT_CONSENTS_FOR_ATHLETE = text(
    """
    SELECT scope FROM consent_grants
     WHERE team_id = :team_id AND athlete_id = :athlete_id AND granted = true
    """
)

_SELECT_LATEST_LOAD = text(
    """
    SELECT date, acute_load, chronic_load, load_ratio, data_quality
      FROM training_load_daily
     WHERE athlete_id = :athlete_id
       AND unit = 'AU'
       AND date <= COALESCE(
             (
               SELECT (CURRENT_TIMESTAMP AT TIME ZONE ap.timezone)::date
                 FROM athlete_profiles ap
                WHERE ap.user_id = :athlete_id
             ),
             CURRENT_DATE
           )
     ORDER BY date DESC
     LIMIT 1
    """
)

_SELECT_LAST_14_LOAD = text(
    """
    SELECT date, session_load
      FROM training_load_daily
     WHERE athlete_id = :athlete_id
       AND unit = 'AU'
       AND date <= COALESCE(
             (
               SELECT (CURRENT_TIMESTAMP AT TIME ZONE ap.timezone)::date
                 FROM athlete_profiles ap
                WHERE ap.user_id = :athlete_id
             ),
             CURRENT_DATE
           )
     ORDER BY date DESC
     LIMIT 14
    """
)

_SELECT_LAST_ACTIVITY_DATE = text(
    "SELECT MAX(local_training_date) AS last_date FROM completed_activities "
    "WHERE athlete_id = :athlete_id AND deleted_at IS NULL"
)

_SELECT_LATEST_INJURY = text(
    """
    SELECT has_issue, severity_band
      FROM injury_reports
     WHERE athlete_id = :athlete_id
     ORDER BY reported_at DESC, id DESC
     LIMIT 1
    """
)

_SELECT_LATEST_INJURY_DETAIL = text(
    "SELECT app_latest_injury_detail_for_actor(:athlete_id) AS free_text"
)

_SELECT_ATHLETE_ACTIVITIES_BY_DATE = text(
    """
    SELECT id, athlete_id, client_mutation_id, provider, provider_activity_id,
           duration_minutes, rpe, performed_at, timezone_snapshot,
           local_training_date, session_load, unit, source_metric,
           server_version, created_at, structure, distance_km, device_metrics
      FROM completed_activities
     WHERE athlete_id = :athlete_id AND deleted_at IS NULL
       AND local_training_date = :local_date
     ORDER BY performed_at DESC, id DESC
    """
)


def _display_name(display_name: str | None, email: str) -> str:
    if display_name:
        return display_name
    return email.split("@", 1)[0]


def _read_gated_fields(
    tx: Connection, athlete_id: uuid.UUID, granted_scopes: set[str]
) -> dict:
    fields: dict = {
        "last_activity_local_date": None,
        "acute_load_au": None,
        "chronic_load_au": None,
        "load_ratio": None,
        "data_quality": None,
        "last_14_days_load": [],
        "injury_has_issue": None,
        "injury_severity_band": None,
        "injury_free_text": None,
    }
    needs_summary = "activity_summary" in granted_scopes
    needs_load = "training_load" in granted_scopes
    needs_injury_status = "injury_status" in granted_scopes
    needs_injury_detail = "injury_detail" in granted_scopes
    if not any((needs_summary, needs_load, needs_injury_status, needs_injury_detail)):
        return fields

    if needs_summary:
        row = tx.execute(_SELECT_LAST_ACTIVITY_DATE, {"athlete_id": athlete_id}).first()
        fields["last_activity_local_date"] = row.last_date if row else None
    if needs_load:
        latest = tx.execute(_SELECT_LATEST_LOAD, {"athlete_id": athlete_id}).first()
        if latest is not None:
            fields["acute_load_au"] = float(latest.acute_load)
            fields["chronic_load_au"] = float(latest.chronic_load)
            fields["load_ratio"] = (
                float(latest.load_ratio) if latest.load_ratio is not None else None
            )
            fields["data_quality"] = latest.data_quality
        last14 = tx.execute(_SELECT_LAST_14_LOAD, {"athlete_id": athlete_id}).all()
        fields["last_14_days_load"] = [float(r.session_load) for r in reversed(last14)]
    if needs_injury_status:
        injury = tx.execute(_SELECT_LATEST_INJURY, {"athlete_id": athlete_id}).first()
        if injury is not None:
            fields["injury_has_issue"] = injury.has_issue
            fields["injury_severity_band"] = injury.severity_band
    if needs_injury_detail:
        detail = tx.execute(
            _SELECT_LATEST_INJURY_DETAIL, {"athlete_id": athlete_id}
        ).first()
        fields["injury_free_text"] = detail.free_text if detail else None
    return fields


def _build_row(
    *,
    team_id: uuid.UUID,
    membership_row,
    granted_scopes: set[str],
    gated_fields: dict,
) -> CoachRosterRowResponse:
    return CoachRosterRowResponse(
        team_id=team_id,
        athlete_id=membership_row.athlete_id,
        name=_display_name(membership_row.display_name, membership_row.email),
        status=membership_row.status,
        joined_at=membership_row.joined_at,
        granted_scopes=sorted(granted_scopes),
        **gated_fields,
    )


@router.get("/mine", response_model=MyTeamsResponse, dependencies=[Depends(require_demo_mfa)])
def list_my_teams(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> MyTeamsResponse:
    """Teams the actor holds a coach-ish Team Role in. Minimal plumbing this
    change adds beyond docs/mvp-checklist.md Item 1's literal two endpoints
    so the web coach screens have a team_id to call the roster/detail
    endpoints with at all -- see this change's final report."""

    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        rows = tx.execute(
            _SELECT_MY_TEAMS, {"actor_id": actor_id}
        ).all()
    return MyTeamsResponse(
        items=[TeamSummaryResponse(team_id=r.team_id, name=r.name, role=r.role) for r in rows]
    )


@router.get(
    "/{team_id}/roster",
    response_model=TeamRosterResponse,
    dependencies=[Depends(require_demo_mfa)],
)
def get_team_roster(
    team_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> TeamRosterResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        require_coach_role(tx, team_id, actor_id)

        # A LEFT (or INVITED) Team Membership is excluded by this WHERE
        # clause, not filtered client-side -- it is genuinely absent from
        # the result set (docs/mvp-checklist.md Item 1, "Enforce" bullet).
        athlete_rows = tx.execute(_SELECT_ACTIVE_ATHLETES, {"team_id": team_id}).all()

        grants_by_athlete: dict[uuid.UUID, set[str]] = defaultdict(set)
        for consent_row in tx.execute(_SELECT_CONSENTS, {"team_id": team_id}):
            grants_by_athlete[consent_row.athlete_id].add(consent_row.scope)
        items = []
        for membership_row in athlete_rows:
            granted_scopes = grants_by_athlete.get(membership_row.athlete_id, set())
            gated_fields = _read_gated_fields(tx, membership_row.athlete_id, granted_scopes)
            items.append(
                _build_row(
                    team_id=team_id,
                    membership_row=membership_row,
                    granted_scopes=granted_scopes,
                    gated_fields=gated_fields,
                )
            )
    return TeamRosterResponse(team_id=team_id, items=items)


@router.get(
    "/{team_id}/athletes/{athlete_id}",
    response_model=CoachRosterRowResponse,
    dependencies=[Depends(require_demo_mfa)],
)
def get_team_athlete(
    team_id: uuid.UUID,
    athlete_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> CoachRosterRowResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        require_coach_role(tx, team_id, actor_id)

        membership_row = tx.execute(
            _SELECT_ONE_ACTIVE_ATHLETE, {"team_id": team_id, "athlete_id": athlete_id}
        ).first()
        if membership_row is None:
            # Same query shape as the roster: a LEFT membership and a
            # never-existed athlete are indistinguishable 404s.
            raise TeamAthleteNotFoundError()

        granted_scopes = {
            consent_row.scope
            for consent_row in tx.execute(
                _SELECT_CONSENTS_FOR_ATHLETE, {"team_id": team_id, "athlete_id": athlete_id}
            )
        }
        gated_fields = _read_gated_fields(tx, athlete_id, granted_scopes)
        return _build_row(
            team_id=team_id,
            membership_row=membership_row,
            granted_scopes=granted_scopes,
            gated_fields=gated_fields,
        )


@router.get(
    "/{team_id}/athletes/{athlete_id}/activities",
    response_model=ActivityHistoryResponse,
    dependencies=[Depends(require_demo_mfa)],
)
def get_team_athlete_activities(
    team_id: uuid.UUID,
    athlete_id: uuid.UUID,
    local_date: date,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> ActivityHistoryResponse:
    """A Coach reading the Completed Activity (if any) that actually
    happened on one Local Training Date -- "did the athlete follow this
    assigned workout, and what did they really do." The verified Actor
    stays the coach throughout; athlete_id/local_date are query values only.
    completed_activities_coach_read independently re-verifies active shared
    Team Membership and a granted 'activity_summary' Consent Scope for every
    row -- if that scope isn't granted, the query below simply returns no
    rows rather than raising, the same posture every other coach-read field
    in this module already takes."""
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        require_coach_role(tx, team_id, actor_id)

        membership_row = tx.execute(
            _SELECT_ONE_ACTIVE_ATHLETE, {"team_id": team_id, "athlete_id": athlete_id}
        ).first()
        if membership_row is None:
            raise TeamAthleteNotFoundError()

        rows = tx.execute(
            _SELECT_ATHLETE_ACTIVITIES_BY_DATE,
            {"athlete_id": athlete_id, "local_date": local_date},
        ).all()
    return ActivityHistoryResponse(
        items=[_row_to_response(row) for row in rows],
        next_cursor=None,
    )

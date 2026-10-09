"""Coach Assignments (AssignedWorkout).

docs/mvp-checklist.md pulled this back into scope from "Deferred past MVP".
See CONTEXT.md's Assigned Workout definition. No PATCH -- AssignmentsScreen.tsx
has no mark-complete/missed or edit interaction, only create, delete, and a
read-only table (see this change's final report for the path-naming
decision, documented in backend/README.md).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import AssignmentAthleteNotEligibleError, AssignmentNotFoundError
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.routes.settings import require_demo_mfa
from app.schemas import (
    AssignedWorkoutListResponse,
    AssignedWorkoutResponse,
    CreateAssignedWorkoutRequest,
)
from app.team_authorization import require_coach_role

router = APIRouter(tags=["assignments"])

_SELECT_ACTIVE_ATHLETE_MEMBERSHIP = text(
    """
    SELECT 1 FROM team_memberships
     WHERE team_id = :team_id
       AND user_id = :athlete_id
       AND role = 'athlete'
       AND status = 'ACTIVE'
    """
)

_INSERT_ASSIGNMENT = text(
    """
    INSERT INTO assigned_workouts (
        team_id, athlete_id, local_date, title, duration_minutes, intensity_label, structure
    ) VALUES (
        :team_id, :athlete_id, :local_date, :title, :duration_minutes, :intensity_label, CAST(:structure AS jsonb)
    )
    RETURNING id, team_id, athlete_id, local_date, title, duration_minutes,
              intensity_label, status, created_at, structure, tracked, notes, batch_id
    """
)

_SELECT_TEAM_ASSIGNMENTS = text(
    """
    SELECT id, team_id, athlete_id, local_date, title, duration_minutes,
           intensity_label, status, created_at, structure, tracked, notes, batch_id
      FROM assigned_workouts
     WHERE team_id = :team_id
     ORDER BY local_date DESC, created_at DESC
    """
)

_DELETE_ASSIGNMENT = text(
    """
    DELETE FROM assigned_workouts
     WHERE id = :assignment_id AND team_id = :team_id
    RETURNING id
    """
)

_SELECT_MY_ASSIGNMENTS = text(
    """
    SELECT id, team_id, athlete_id, local_date, title, duration_minutes,
           intensity_label, status, created_at, structure, tracked, notes, batch_id
      FROM assigned_workouts
     WHERE athlete_id = :athlete_id
     ORDER BY local_date DESC, created_at DESC
    """
)


def _row_to_response(row) -> AssignedWorkoutResponse:
    return AssignedWorkoutResponse(
        id=row.id,
        team_id=row.team_id,
        athlete_id=row.athlete_id,
        local_date=row.local_date,
        title=row.title,
        duration_minutes=row.duration_minutes,
        intensity_label=row.intensity_label,
        status=row.status,
        created_at=row.created_at,
        structure=row.structure or [],
        tracked=row.tracked,
        notes=row.notes,
        batch_id=row.batch_id,
    )


@router.post(
    "/teams/{team_id}/assignments",
    response_model=AssignedWorkoutResponse,
    status_code=201,
    dependencies=[Depends(require_demo_mfa)],
)
def create_assignment(
    team_id: uuid.UUID,
    payload: CreateAssignedWorkoutRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> AssignedWorkoutResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        require_coach_role(tx, team_id, actor_id)

        eligible = tx.execute(
            _SELECT_ACTIVE_ATHLETE_MEMBERSHIP,
            {"team_id": team_id, "athlete_id": payload.athlete_id},
        ).first()
        if eligible is None:
            # A departed (LEFT) or never-a-member athlete looks identical --
            # same non-leak posture as TeamAthleteNotFoundError.
            raise AssignmentAthleteNotEligibleError()

        inserted = tx.execute(
            _INSERT_ASSIGNMENT,
            {
                "team_id": team_id,
                "athlete_id": payload.athlete_id,
                "local_date": payload.local_date,
                "title": payload.title,
                "duration_minutes": payload.duration_minutes,
                "intensity_label": payload.intensity_label,
                "structure": __import__("json").dumps(payload.structure),
            },
        ).first()
        return _row_to_response(inserted)


@router.delete(
    "/teams/{team_id}/assignments/{assignment_id}",
    status_code=204,
    dependencies=[Depends(require_demo_mfa)],
)
def delete_assignment(
    team_id: uuid.UUID,
    assignment_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> None:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        require_coach_role(tx, team_id, actor_id)
        row = tx.execute(
            _DELETE_ASSIGNMENT,
            {"assignment_id": assignment_id, "team_id": team_id},
        ).first()
    if row is None:
        # Not this team's assignment (or already deleted) -- same non-leak
        # posture as SessionNotFoundError.
        raise AssignmentNotFoundError()


@router.get(
    "/teams/{team_id}/assignments",
    response_model=AssignedWorkoutListResponse,
    dependencies=[Depends(require_demo_mfa)],
)
def list_team_assignments(
    team_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> AssignedWorkoutListResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        require_coach_role(tx, team_id, actor_id)
        rows = tx.execute(_SELECT_TEAM_ASSIGNMENTS, {"team_id": team_id}).all()
    return AssignedWorkoutListResponse(items=[_row_to_response(row) for row in rows])


@router.get("/me/assigned-workouts", response_model=AssignedWorkoutListResponse)
def list_my_assigned_workouts(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> AssignedWorkoutListResponse:
    """The athlete's own view of assignments made to them, across any team.

    The explicit "assigned-workouts" path keeps this Team-owned concept
    distinct from membership and consent resources under `/me`."""

    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        rows = tx.execute(_SELECT_MY_ASSIGNMENTS, {"athlete_id": actor_id}).all()
    return AssignedWorkoutListResponse(items=[_row_to_response(row) for row in rows])

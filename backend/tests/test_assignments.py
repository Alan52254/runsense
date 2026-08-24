"""DB-dependent tests for Coach Assignments (AssignedWorkout)
(docs/mvp-checklist.md, pulled back into scope from "Deferred past MVP").
See backend/app/routes/assignments.py.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text

from conftest import requires_db


def _insert_user(admin_engine, user_id) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": user_id, "email": f"{user_id}@example.test"},
        )


def _insert_team(admin_engine, team_id, name) -> None:
    with admin_engine.begin() as conn:
        conn.execute(text("INSERT INTO teams (id, name) VALUES (:id, :name)"), {"id": team_id, "name": name})


def _insert_membership(admin_engine, team_id, user_id, role, status="ACTIVE") -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) "
                "VALUES (:team_id, :user_id, :role, :status, now())"
            ),
            {"team_id": team_id, "user_id": user_id, "role": role, "status": status},
        )


def _setup_team_with_coach_and_athlete(admin_engine, *, athlete_status="ACTIVE"):
    team_id = uuid.uuid4()
    coach_id = uuid.uuid4()
    athlete_id = uuid.uuid4()
    _insert_user(admin_engine, coach_id)
    _insert_user(admin_engine, athlete_id)
    _insert_team(admin_engine, team_id, f"team-{team_id}")
    _insert_membership(admin_engine, team_id, coach_id, "coach")
    _insert_membership(admin_engine, team_id, athlete_id, "athlete", status=athlete_status)
    return team_id, coach_id, athlete_id


_PAYLOAD = {
    "local_date": date.today().isoformat(),
    "title": "Easy 5k",
    "duration_minutes": 30,
    "intensity_label": "RPE 3-4",
}


@requires_db
def test_coach_can_create_assignment_for_active_athlete(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup_team_with_coach_and_athlete(admin_engine)

    client = make_client(actor_id=str(coach_id))
    response = client.post(
        f"/teams/{team_id}/assignments",
        json={**_PAYLOAD, "athlete_id": str(athlete_id)},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["team_id"] == str(team_id)
    assert body["athlete_id"] == str(athlete_id)
    assert body["status"] == "SCHEDULED"
    assert body["title"] == "Easy 5k"


@requires_db
def test_non_coach_cannot_create_assignment(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup_team_with_coach_and_athlete(admin_engine)

    client = make_client(actor_id=str(athlete_id))
    response = client.post(
        f"/teams/{team_id}/assignments",
        json={**_PAYLOAD, "athlete_id": str(athlete_id)},
    )
    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_cannot_assign_to_a_left_athlete(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup_team_with_coach_and_athlete(
        admin_engine, athlete_status="LEFT"
    )

    client = make_client(actor_id=str(coach_id))
    response = client.post(
        f"/teams/{team_id}/assignments",
        json={**_PAYLOAD, "athlete_id": str(athlete_id)},
    )
    assert response.status_code == 404
    assert response.json() == {"error": "ASSIGNMENT_ATHLETE_NOT_ELIGIBLE"}


@requires_db
def test_cannot_assign_to_an_athlete_not_on_the_team(make_client, admin_engine):
    team_id, coach_id, _athlete_id = _setup_team_with_coach_and_athlete(admin_engine)
    stranger_id = uuid.uuid4()
    _insert_user(admin_engine, stranger_id)

    client = make_client(actor_id=str(coach_id))
    response = client.post(
        f"/teams/{team_id}/assignments",
        json={**_PAYLOAD, "athlete_id": str(stranger_id)},
    )
    assert response.status_code == 404
    assert response.json() == {"error": "ASSIGNMENT_ATHLETE_NOT_ELIGIBLE"}


@requires_db
def test_coach_lists_team_assignments(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup_team_with_coach_and_athlete(admin_engine)
    client = make_client(actor_id=str(coach_id))
    created = client.post(
        f"/teams/{team_id}/assignments",
        json={**_PAYLOAD, "athlete_id": str(athlete_id)},
    )
    assert created.status_code == 201

    listing = client.get(f"/teams/{team_id}/assignments")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["athlete_id"] == str(athlete_id)


@requires_db
def test_non_coach_cannot_list_team_assignments(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup_team_with_coach_and_athlete(admin_engine)
    client = make_client(actor_id=str(athlete_id))
    response = client.get(f"/teams/{team_id}/assignments")
    assert response.status_code == 403


@requires_db
def test_athlete_sees_own_assigned_workouts_across_teams(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup_team_with_coach_and_athlete(admin_engine)
    coach_client = make_client(actor_id=str(coach_id))
    created = coach_client.post(
        f"/teams/{team_id}/assignments",
        json={**_PAYLOAD, "athlete_id": str(athlete_id)},
    )
    assert created.status_code == 201

    athlete_client = make_client(actor_id=str(athlete_id))
    mine = athlete_client.get("/me/assigned-workouts")
    assert mine.status_code == 200
    items = mine.json()["items"]
    assert len(items) == 1
    assert items[0]["team_id"] == str(team_id)


@requires_db
def test_athlete_with_no_assignments_sees_empty_list(make_client, admin_engine):
    athlete_id = uuid.uuid4()
    _insert_user(admin_engine, athlete_id)
    client = make_client(actor_id=str(athlete_id))
    response = client.get("/me/assigned-workouts")
    assert response.status_code == 200
    assert response.json()["items"] == []


@requires_db
def test_create_assignment_rejects_unknown_fields(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup_team_with_coach_and_athlete(admin_engine)
    client = make_client(actor_id=str(coach_id))
    response = client.post(
        f"/teams/{team_id}/assignments",
        json={**_PAYLOAD, "athlete_id": str(athlete_id), "status": "COMPLETED"},
    )
    assert response.status_code == 422

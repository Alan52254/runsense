"""DB-dependent tests for docs/mvp-checklist.md Backlog Item 1: Coach Team
Overview + Coach Athlete Detail. Requires TEST_DATABASE_URL / DATABASE_URL
pointing at a Postgres instance with migrations applied (alembic upgrade
head).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from conftest import requires_db


def _insert_user(admin_engine, *, email: str, display_name: str | None = None) -> uuid.UUID:
    user_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:id, :email, 'x', :display_name)"
            ),
            {"id": user_id, "email": email, "display_name": display_name},
        )
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:id, 'UTC')"),
            {"id": user_id},
        )
    return user_id


def _insert_team(admin_engine, *, name: str) -> uuid.UUID:
    team_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO teams (id, name) VALUES (:id, :name)"),
            {"id": team_id, "name": name},
        )
    return team_id


def _insert_membership(
    admin_engine,
    *,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    status: str,
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) "
                "VALUES (:team_id, :user_id, :role, :status, "
                "CASE WHEN :status = 'ACTIVE' THEN now() ELSE NULL END)"
            ),
            {"team_id": team_id, "user_id": user_id, "role": role, "status": status},
        )


def _insert_consent(
    admin_engine, *, team_id: uuid.UUID, athlete_id: uuid.UUID, scope: str, granted: bool
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO consent_grants (team_id, athlete_id, scope, granted) "
                "VALUES (:team_id, :athlete_id, :scope, :granted)"
            ),
            {"team_id": team_id, "athlete_id": athlete_id, "scope": scope, "granted": granted},
        )


def _insert_training_load_point(admin_engine, *, athlete_id: uuid.UUID, on_date, session_load: float) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO training_load_daily (
                    athlete_id, date, unit, session_load, source_metric,
                    acute_load, chronic_load, load_ratio, data_quality,
                    observation_days, algorithm_version, schema_version,
                    computed_at, input_snapshot_hash
                ) VALUES (
                    :athlete_id, :date, 'AU', :session_load, 'SESSION_RPE',
                    :session_load, :session_load, 1.0, 'SUFFICIENT',
                    21, 'tl-v1', 1, now(), :hash
                )
                """
            ),
            {
                "athlete_id": athlete_id,
                "date": on_date,
                "session_load": Decimal(str(session_load)),
                "hash": "0" * 64,
            },
        )


@requires_db
def test_roster_lists_only_active_athletes_and_excludes_left(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Roster Team A")
    coach_id = _insert_user(admin_engine, email="coach-a@runsense.demo")
    active_athlete = _insert_user(admin_engine, email="active-a@runsense.demo", display_name="Active Athlete")
    left_athlete = _insert_user(admin_engine, email="left-a@runsense.demo", display_name="Left Athlete")
    invited_athlete = _insert_user(admin_engine, email="invited-a@runsense.demo")

    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="head_coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=active_athlete, role="athlete", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=left_athlete, role="athlete", status="LEFT")
    _insert_membership(admin_engine, team_id=team_id, user_id=invited_athlete, role="athlete", status="INVITED")

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(f"/teams/{team_id}/roster")
    assert response.status_code == 200, response.text
    body = response.json()
    athlete_ids = {item["athlete_id"] for item in body["items"]}

    assert str(active_athlete) in athlete_ids
    assert str(left_athlete) not in athlete_ids, "LEFT membership must be genuinely absent, not just masked"
    assert str(invited_athlete) not in athlete_ids
    assert len(body["items"]) == 1


@requires_db
def test_roster_field_gating_only_includes_granted_scope_fields(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Roster Team B")
    coach_id = _insert_user(admin_engine, email="coach-b@runsense.demo")
    athlete_id = _insert_user(admin_engine, email="athlete-b@runsense.demo", display_name="Gated Athlete")

    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")

    # Only activity_summary granted -- training_load is NOT granted.
    _insert_consent(admin_engine, team_id=team_id, athlete_id=athlete_id, scope="activity_summary", granted=True)
    _insert_consent(admin_engine, team_id=team_id, athlete_id=athlete_id, scope="training_load", granted=False)

    today = datetime.now(timezone.utc).date()
    _insert_training_load_point(admin_engine, athlete_id=athlete_id, on_date=today, session_load=270)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO completed_activities "
                "(athlete_id, client_mutation_id, request_fingerprint, duration_minutes, rpe, "
                " performed_at, timezone_snapshot, local_training_date, session_load) "
                "VALUES (:athlete_id, :cmid, 'fp', 45, 6, now(), 'UTC', :date, 270)"
            ),
            {"athlete_id": athlete_id, "cmid": str(uuid.uuid4()), "date": today},
        )

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(f"/teams/{team_id}/roster")
    assert response.status_code == 200, response.text
    row = response.json()["items"][0]

    assert row["granted_scopes"] == ["activity_summary"]
    assert row["last_activity_local_date"] == str(today), "activity_summary was granted"
    assert row["acute_load_au"] is None, "training_load was NOT granted"
    assert row["chronic_load_au"] is None
    assert row["load_ratio"] is None
    assert row["data_quality"] is None
    assert row["last_14_days_load"] == []


@requires_db
def test_roster_rejects_actor_without_coach_role_in_team(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Roster Team C")
    outsider_id = _insert_user(admin_engine, email="outsider-c@runsense.demo")

    client = make_client(actor_id=str(outsider_id), timezones={str(outsider_id): "UTC"})
    response = client.get(f"/teams/{team_id}/roster")
    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_roster_rejects_athlete_role_actor_even_if_member_of_team(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Roster Team D")
    athlete_only_id = _insert_user(admin_engine, email="athlete-only-d@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_only_id, role="athlete", status="ACTIVE")

    client = make_client(actor_id=str(athlete_only_id), timezones={str(athlete_only_id): "UTC"})
    response = client.get(f"/teams/{team_id}/roster")
    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_athlete_detail_returns_404_for_left_membership(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Roster Team E")
    coach_id = _insert_user(admin_engine, email="coach-e@runsense.demo")
    left_athlete = _insert_user(admin_engine, email="left-e@runsense.demo")

    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="owner", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=left_athlete, role="athlete", status="LEFT")

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(f"/teams/{team_id}/athletes/{left_athlete}")
    assert response.status_code == 404
    assert response.json() == {"error": "TEAM_ATHLETE_NOT_FOUND"}


@requires_db
def test_athlete_detail_returns_404_for_athlete_never_in_team(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Roster Team F")
    coach_id = _insert_user(admin_engine, email="coach-f@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="head_coach", status="ACTIVE")

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(f"/teams/{team_id}/athletes/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"error": "TEAM_ATHLETE_NOT_FOUND"}


@requires_db
def test_athlete_detail_matches_roster_projection_for_fully_granted_athlete(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Roster Team G")
    coach_id = _insert_user(admin_engine, email="coach-g@runsense.demo")
    athlete_id = _insert_user(admin_engine, email="athlete-g@runsense.demo", display_name="Full Grant Athlete")

    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")
    for scope in ("activity_summary", "training_load", "injury_status", "injury_detail"):
        _insert_consent(admin_engine, team_id=team_id, athlete_id=athlete_id, scope=scope, granted=True)

    today = datetime.now(timezone.utc).date()
    for offset in range(3):
        _insert_training_load_point(
            admin_engine, athlete_id=athlete_id, on_date=today - timedelta(days=offset), session_load=100 + offset
        )

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    roster = client.get(f"/teams/{team_id}/roster")
    detail = client.get(f"/teams/{team_id}/athletes/{athlete_id}")
    assert roster.status_code == 200 and detail.status_code == 200

    roster_row = roster.json()["items"][0]
    detail_row = detail.json()
    assert roster_row == detail_row
    assert detail_row["name"] == "Full Grant Athlete"
    assert set(detail_row["granted_scopes"]) == {
        "activity_summary",
        "training_load",
        "injury_status",
        "injury_detail",
    }
    assert detail_row["acute_load_au"] == 100.0
    assert len(detail_row["last_14_days_load"]) == 3


@requires_db
def test_roster_ignores_materialized_training_load_after_athletes_local_today(
    make_client, admin_engine
):
    team_id = _insert_team(admin_engine, name="Roster Team Future Load")
    coach_id = _insert_user(admin_engine, email="coach-future@runsense.demo")
    athlete_id = _insert_user(admin_engine, email="athlete-future@runsense.demo")
    _insert_membership(
        admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE"
    )
    _insert_membership(
        admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE"
    )
    _insert_consent(
        admin_engine,
        team_id=team_id,
        athlete_id=athlete_id,
        scope="training_load",
        granted=True,
    )

    today = datetime.now(timezone.utc).date()
    _insert_training_load_point(
        admin_engine, athlete_id=athlete_id, on_date=today, session_load=123
    )
    _insert_training_load_point(
        admin_engine,
        athlete_id=athlete_id,
        on_date=today + timedelta(days=1),
        session_load=999,
    )

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(f"/teams/{team_id}/roster")
    assert response.status_code == 200, response.text
    row = response.json()["items"][0]

    assert row["acute_load_au"] == 123.0
    assert row["last_14_days_load"] == [123.0]


@requires_db
def test_teams_mine_lists_only_coach_ish_teams_not_athlete_only_teams(make_client, admin_engine):
    coach_team = _insert_team(admin_engine, name="Mine Team A")
    athlete_only_team = _insert_team(admin_engine, name="Mine Team B")
    user_id = _insert_user(admin_engine, email="mixed-role@runsense.demo")

    _insert_membership(admin_engine, team_id=coach_team, user_id=user_id, role="head_coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=athlete_only_team, user_id=user_id, role="athlete", status="ACTIVE")

    client = make_client(actor_id=str(user_id), timezones={str(user_id): "UTC"})
    response = client.get("/teams/mine")
    assert response.status_code == 200, response.text
    team_ids = {item["team_id"] for item in response.json()["items"]}
    assert str(coach_team) in team_ids
    assert str(athlete_only_team) not in team_ids


def _insert_completed_activity(
    admin_engine, *, athlete_id: uuid.UUID, on_date, duration_minutes: int, rpe: int
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO completed_activities "
                "(athlete_id, client_mutation_id, request_fingerprint, duration_minutes, rpe, "
                " performed_at, timezone_snapshot, local_training_date, session_load) "
                "VALUES (:athlete_id, :cmid, :fp, :duration_minutes, :rpe, now(), 'UTC', :date, :load)"
            ),
            {
                "athlete_id": athlete_id,
                "cmid": str(uuid.uuid4()),
                "fp": f"fp-{uuid.uuid4()}",
                "duration_minutes": duration_minutes,
                "rpe": rpe,
                "date": on_date,
                "load": duration_minutes * rpe,
            },
        )


@requires_db
def test_athlete_activities_by_date_returns_the_matching_activity(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Activities Team A")
    coach_id = _insert_user(admin_engine, email="coach-act-a@runsense.demo")
    athlete_id = _insert_user(admin_engine, email="athlete-act-a@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")
    _insert_consent(admin_engine, team_id=team_id, athlete_id=athlete_id, scope="activity_summary", granted=True)

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    _insert_completed_activity(admin_engine, athlete_id=athlete_id, on_date=today, duration_minutes=45, rpe=6)
    _insert_completed_activity(admin_engine, athlete_id=athlete_id, on_date=yesterday, duration_minutes=30, rpe=4)

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(
        f"/teams/{team_id}/athletes/{athlete_id}/activities", params={"local_date": str(today)}
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["local_training_date"] == str(today)
    assert items[0]["duration_minutes"] == 45


@requires_db
def test_athlete_activities_by_date_empty_when_no_activity_that_day(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Activities Team B")
    coach_id = _insert_user(admin_engine, email="coach-act-b@runsense.demo")
    athlete_id = _insert_user(admin_engine, email="athlete-act-b@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")
    _insert_consent(admin_engine, team_id=team_id, athlete_id=athlete_id, scope="activity_summary", granted=True)

    today = datetime.now(timezone.utc).date()
    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(
        f"/teams/{team_id}/athletes/{athlete_id}/activities", params={"local_date": str(today)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


@requires_db
def test_athlete_activities_by_date_empty_when_activity_summary_not_granted(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Activities Team C")
    coach_id = _insert_user(admin_engine, email="coach-act-c@runsense.demo")
    athlete_id = _insert_user(admin_engine, email="athlete-act-c@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")
    # No consent_grants row at all for activity_summary -- the RLS policy
    # must filter these rows out, not just the roster's field-gating layer.

    today = datetime.now(timezone.utc).date()
    _insert_completed_activity(admin_engine, athlete_id=athlete_id, on_date=today, duration_minutes=45, rpe=6)

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(
        f"/teams/{team_id}/athletes/{athlete_id}/activities", params={"local_date": str(today)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [], "activity_summary was never granted -- RLS must hide the row"


@requires_db
def test_athlete_activities_by_date_returns_404_for_athlete_never_in_team(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Activities Team D")
    coach_id = _insert_user(admin_engine, email="coach-act-d@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="head_coach", status="ACTIVE")

    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    response = client.get(
        f"/teams/{team_id}/athletes/{uuid.uuid4()}/activities",
        params={"local_date": str(datetime.now(timezone.utc).date())},
    )
    assert response.status_code == 404
    assert response.json() == {"error": "TEAM_ATHLETE_NOT_FOUND"}


@requires_db
def test_athlete_activities_by_date_rejects_actor_without_coach_role(make_client, admin_engine):
    team_id = _insert_team(admin_engine, name="Activities Team E")
    athlete_id = _insert_user(admin_engine, email="athlete-act-e@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")

    client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "UTC"})
    response = client.get(
        f"/teams/{team_id}/athletes/{athlete_id}/activities",
        params={"local_date": str(datetime.now(timezone.utc).date())},
    )
    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_cross_team_actor_cannot_read_another_teams_roster(make_client, admin_engine):
    team_a = _insert_team(admin_engine, name="Cross Team A")
    team_b = _insert_team(admin_engine, name="Cross Team B")
    coach_a = _insert_user(admin_engine, email="coach-cross-a@runsense.demo")
    athlete_b = _insert_user(admin_engine, email="athlete-cross-b@runsense.demo")

    _insert_membership(admin_engine, team_id=team_a, user_id=coach_a, role="head_coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_b, user_id=athlete_b, role="athlete", status="ACTIVE")

    client = make_client(actor_id=str(coach_a), timezones={str(coach_a): "UTC"})
    response = client.get(f"/teams/{team_b}/roster")
    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}

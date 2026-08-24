from __future__ import annotations

import uuid

from sqlalchemy import text

from conftest import requires_db


SCOPES = ("activity_summary", "training_load", "injury_status", "injury_detail")


def _seed_team(admin_engine, *, membership_status: str = "ACTIVE") -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    team_id, athlete_id, coach_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) VALUES "
                "(:athlete, :athlete_email, 'x', 'Athlete'), "
                "(:coach, :coach_email, 'x', 'Coach')"
            ),
            {
                "athlete": athlete_id,
                "athlete_email": f"athlete-{athlete_id}@example.test",
                "coach": coach_id,
                "coach_email": f"coach-{coach_id}@example.test",
            },
        )
        conn.execute(
            text(
                "INSERT INTO athlete_profiles (user_id, timezone) VALUES "
                "(:athlete, 'Asia/Taipei'), (:coach, 'Asia/Taipei')"
            ),
            {"athlete": athlete_id, "coach": coach_id},
        )
        conn.execute(text("INSERT INTO teams (id, name) VALUES (:id, 'Stride Lab')"), {"id": team_id})
        conn.execute(
            text(
                "INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) VALUES "
                "(:team, :coach, 'head_coach', 'ACTIVE', now()), "
                "(:team, :athlete, 'athlete', :status, CASE WHEN :status = 'ACTIVE' THEN now() END)"
            ),
            {"team": team_id, "coach": coach_id, "athlete": athlete_id, "status": membership_status},
        )
        for scope in SCOPES:
            conn.execute(
                text(
                    "INSERT INTO consent_grants (team_id, athlete_id, scope, granted) "
                    "VALUES (:team, :athlete, :scope, false)"
                ),
                {"team": team_id, "athlete": athlete_id, "scope": scope},
            )
    return team_id, athlete_id, coach_id


@requires_db
def test_athlete_can_list_memberships_and_independent_consent(make_client, admin_engine):
    team_id, athlete_id, _ = _seed_team(admin_engine)
    client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})

    memberships = client.get("/me/team-memberships")
    consents = client.get("/me/consent-grants")

    assert memberships.status_code == 200, memberships.text
    assert memberships.json()["items"] == [
        {
            "team_id": str(team_id),
            "team_name": "Stride Lab",
            "coach_name": "Coach",
            "role": "athlete",
            "status": "ACTIVE",
            "invited_at": memberships.json()["items"][0]["invited_at"],
            "joined_at": memberships.json()["items"][0]["joined_at"],
            "left_at": None,
        }
    ]
    assert {item["scope"] for item in consents.json()["items"]} == set(SCOPES)
    assert all(item["granted"] is False for item in consents.json()["items"])


@requires_db
def test_consent_revoke_is_visible_to_next_coach_roster_request(make_client, admin_engine):
    team_id, athlete_id, coach_id = _seed_team(admin_engine)
    athlete_client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})

    granted = athlete_client.patch(
        "/me/consent-grants/training_load",
        json={"team_id": str(team_id), "granted": True},
    )
    assert granted.status_code == 200, granted.text

    coach_client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "Asia/Taipei"})
    first = coach_client.get(f"/teams/{team_id}/roster")
    assert first.status_code == 200, first.text
    assert first.json()["items"][0]["granted_scopes"] == ["training_load"]

    athlete_client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    revoked = athlete_client.patch(
        "/me/consent-grants/training_load",
        json={"team_id": str(team_id), "granted": False},
    )
    assert revoked.status_code == 200, revoked.text

    coach_client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "Asia/Taipei"})
    second = coach_client.get(f"/teams/{team_id}/roster")
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["granted_scopes"] == []

    with admin_engine.connect() as conn:
        events = conn.execute(
            text("SELECT event FROM audit_log WHERE actor_id=:actor ORDER BY created_at"),
            {"actor": athlete_id},
        ).scalars().all()
    assert events == ["CONSENT_GRANT", "CONSENT_REVOKE"]


@requires_db
def test_leaving_team_revokes_all_scopes_and_removes_roster_row(make_client, admin_engine):
    team_id, athlete_id, coach_id = _seed_team(admin_engine)
    athlete_client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    for scope in SCOPES:
        response = athlete_client.patch(
            f"/me/consent-grants/{scope}",
            json={"team_id": str(team_id), "granted": True},
        )
        assert response.status_code == 200, response.text

    left = athlete_client.patch(
        f"/me/team-memberships/{team_id}",
        json={"action": "leave"},
    )
    assert left.status_code == 200, left.text
    assert left.json()["status"] == "LEFT"

    coach_client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "Asia/Taipei"})
    roster = coach_client.get(f"/teams/{team_id}/roster")
    assert roster.status_code == 200, roster.text
    assert roster.json()["items"] == []

    with admin_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM consent_grants WHERE athlete_id=:athlete AND granted"),
            {"athlete": athlete_id},
        ).scalar_one() == 0


@requires_db
def test_invited_athlete_can_accept_but_cannot_grant_before_accepting(make_client, admin_engine):
    team_id, athlete_id, _ = _seed_team(admin_engine, membership_status="INVITED")
    client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})

    before = client.patch(
        "/me/consent-grants/activity_summary",
        json={"team_id": str(team_id), "granted": True},
    )
    assert before.status_code == 403

    accepted = client.patch(
        f"/me/team-memberships/{team_id}",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ACTIVE"

    after = client.patch(
        "/me/consent-grants/activity_summary",
        json={"team_id": str(team_id), "granted": True},
    )
    assert after.status_code == 200, after.text

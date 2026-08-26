"""DB-dependent tests for PATCH /profile. See tasks.md 2.3/2.4."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from conftest import requires_db


def _insert_athlete_profile(admin_engine, user_id, timezone_name: str = "Asia/Taipei"):
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": user_id, "email": f"{user_id}@example.test"},
        )
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:id, :tz)"),
            {"id": user_id, "tz": timezone_name},
        )


@requires_db
def test_updating_city_persists_and_leaves_timezone_unchanged(make_client, admin_engine):
    athlete_id = uuid.uuid4()
    _insert_athlete_profile(admin_engine, athlete_id, "Asia/Tokyo")

    client = make_client(actor_id=str(athlete_id))
    response = client.patch("/profile", json={"city": "Taipei"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["city"] == "Taipei"
    assert body["timezone"] == "Asia/Tokyo"


@requires_db
def test_updating_timezone_leaves_city_unchanged(make_client, admin_engine):
    athlete_id = uuid.uuid4()
    _insert_athlete_profile(admin_engine, athlete_id, "Asia/Tokyo")

    client = make_client(actor_id=str(athlete_id))
    first = client.patch("/profile", json={"city": "Taipei"})
    assert first.status_code == 200

    second = client.patch("/profile", json={"timezone": "Europe/London"})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["timezone"] == "Europe/London"
    assert body["city"] == "Taipei"


@requires_db
def test_empty_body_is_rejected_not_treated_as_a_no_op_success(make_client, admin_engine):
    athlete_id = uuid.uuid4()
    _insert_athlete_profile(admin_engine, athlete_id)

    client = make_client(actor_id=str(athlete_id))
    response = client.patch("/profile", json={})
    assert response.status_code == 422
    assert response.json() == {"error": "EMPTY_PROFILE_UPDATE"}


@requires_db
def test_unknown_field_is_rejected(make_client, admin_engine):
    athlete_id = uuid.uuid4()
    _insert_athlete_profile(admin_engine, athlete_id)

    client = make_client(actor_id=str(athlete_id))
    response = client.patch("/profile", json={"city": "Taipei", "unexpected": "x"})
    assert response.status_code == 422


@requires_db
def test_missing_actor_context_is_rejected(make_client):
    assert make_client(actor_id=None).patch("/profile", json={"city": "Taipei"}).status_code == 403

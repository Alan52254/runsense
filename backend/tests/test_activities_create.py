"""DB-dependent tests. Requires TEST_DATABASE_URL / DATABASE_URL pointing at
a Postgres instance with migrations applied (alembic upgrade head).
"""

from __future__ import annotations

import uuid

from conftest import requires_db


@requires_db
def test_tc_load_session_001_session_load_computed(make_client, new_athlete_id):
    """TC-LOAD-SESSION-001: 45 x 6 = 270 AU, source_metric=SESSION_RPE."""
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    resp = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["session_load"] == 270
    assert body["unit"] == "AU"
    assert body["source_metric"] == "SESSION_RPE"
    assert body["athlete_id"] == new_athlete_id
    assert body["provider"] == "manual"
    assert body["provider_activity_id"] is None


@requires_db
def test_athlete_id_field_in_request_is_rejected(make_client, new_athlete_id):
    other_athlete_id = str(uuid.uuid4())
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    resp = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
            "athlete_id": other_athlete_id,
        },
    )
    # extra="forbid" on the request model rejects the unknown field outright
    # -- no record is created, regardless of the supplied athlete_id's value.
    assert resp.status_code == 422


@requires_db
def test_tc_tz_001_local_training_date_from_profile_timezone(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    # 2026-08-07T23:30:00+08:00 == 2026-08-07T15:30:00Z: same UTC calendar
    # date, but chosen so the boundary-crossing case below is meaningful.
    resp = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 30,
            "rpe": 5,
            "performed_at": "2026-08-07T16:30:00Z",  # 2026-08-08 00:30 in Asia/Taipei
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["local_training_date"] == "2026-08-08"
    assert body["timezone_snapshot"] == "Asia/Taipei"


@requires_db
def test_tc_tz_001_later_timezone_change_does_not_rewrite_history(
    make_client, new_athlete_id, admin_engine
):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    resp = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 30,
            "rpe": 5,
            "performed_at": "2026-08-07T16:30:00Z",
        },
    )
    assert resp.status_code == 201
    original = resp.json()

    # Athlete's profile timezone "changes" -- a second create as this athlete
    # now resolves against Tokyo. This change has no PATCH/edit endpoint, so
    # the only way the earlier row's local_training_date/timezone_snapshot
    # could be affected is if the create path itself recomputed existing
    # rows; it doesn't. Verify directly against storage (superuser
    # connection bypasses RLS) rather than through a GET endpoint that
    # doesn't exist in this create-only slice.
    client_after_move = make_client(
        actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Tokyo"}
    )
    second = client_after_move.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 20,
            "rpe": 4,
            "performed_at": "2026-08-09T02:00:00Z",
        },
    )
    assert second.status_code == 201

    from sqlalchemy import text

    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT local_training_date, timezone_snapshot FROM completed_activities WHERE id = :id"
            ),
            {"id": original["id"]},
        ).one()
    assert str(row.local_training_date) == original["local_training_date"]
    assert row.timezone_snapshot == "Asia/Taipei"


@requires_db
def test_tc_tz_002_missing_profile_timezone_rejected(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={})
    resp = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "PROFILE_TIMEZONE_NOT_SET"


@requires_db
def test_tc_idempotency_001_identical_replay_returns_existing_row(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    mutation_id = str(uuid.uuid4())
    payload = {
        "client_mutation_id": mutation_id,
        "duration_minutes": 45,
        "rpe": 6,
        "performed_at": "2026-08-07T09:15:00Z",
    }
    first = client.post("/activities", json=payload)
    assert first.status_code == 201
    second = client.post("/activities", json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


@requires_db
def test_tc_idempotency_001_key_reuse_with_different_payload_rejected(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    mutation_id = str(uuid.uuid4())
    first = client.post(
        "/activities",
        json={
            "client_mutation_id": mutation_id,
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/activities",
        json={
            "client_mutation_id": mutation_id,
            "duration_minutes": 60,  # different payload, same key
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
    assert body["existing_id"] == first.json()["id"]


@requires_db
def test_tc_idempotency_002_format_variance_does_not_produce_409(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    mutation_id = str(uuid.uuid4())
    first = client.post(
        "/activities",
        json={
            "client_mutation_id": mutation_id,
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/activities",
        json={
            "client_mutation_id": mutation_id,
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00+00:00",  # same instant, different format
        },
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


@requires_db
def test_tc_rls_cast_001_malformed_actor_fails_closed_cleanly(make_client):
    client = make_client(actor_id="not-a-uuid", timezones={})
    resp = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_tc_rls_012_missing_actor_context_fails_closed(make_client):
    client = make_client(actor_id=None, timezones={})
    resp = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "NOT_AUTHORIZED"}

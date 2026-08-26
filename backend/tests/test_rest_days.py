from __future__ import annotations

import uuid

from sqlalchemy import text

from conftest import requires_db


@requires_db
def test_confirm_and_revoke_rest_are_idempotent_desired_state(
    make_client, admin_engine, new_athlete_id
):
    client = make_client(actor_id=new_athlete_id, timezones={})
    first = client.put("/rest-days/2026-08-01", json={"confirmed": True})
    assert first.status_code == 200
    assert first.json() == {"date": "2026-08-01", "confirmed": True}
    with admin_engine.connect() as conn:
        before = conn.execute(
            text(
                "SELECT max(computed_at) FROM training_load_daily WHERE athlete_id=:id"
            ),
            {"id": new_athlete_id},
        ).scalar_one()
    retry = client.put("/rest-days/2026-08-01", json={"confirmed": True})
    assert retry.status_code == 200
    with admin_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM athlete_rest_days WHERE athlete_id=:id"),
            {"id": new_athlete_id},
        ).scalar_one() == 1
        assert conn.execute(
            text(
                "SELECT max(computed_at) FROM training_load_daily WHERE athlete_id=:id"
            ),
            {"id": new_athlete_id},
        ).scalar_one() == before

    removed = client.put("/rest-days/2026-08-01", json={"confirmed": False})
    absent_retry = client.put("/rest-days/2026-08-01", json={"confirmed": False})
    assert removed.json()["confirmed"] is False
    assert absent_retry.status_code == 200
    with admin_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM athlete_rest_days WHERE athlete_id=:id"),
            {"id": new_athlete_id},
        ).scalar_one() == 0


@requires_db
def test_rest_confirmation_conflicts_with_existing_activity_and_preserves_it(
    make_client, admin_engine, new_athlete_id
):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "UTC"})
    created = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 10,
            "rpe": 5,
            "performed_at": "2026-08-01T10:00:00Z",
        },
    )
    assert created.status_code == 201
    conflict = client.put("/rest-days/2026-08-01", json={"confirmed": True})
    assert conflict.status_code == 409
    assert conflict.json() == {"error": "REST_DAY_CONFLICTS_WITH_ACTIVITY"}
    with admin_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM completed_activities WHERE athlete_id=:id"),
            {"id": new_athlete_id},
        ).scalar_one() == 1


@requires_db
def test_rest_interface_fails_closed_rejects_forged_actor_and_isolates_athletes(
    make_client, admin_engine
):
    athlete_a, athlete_b = str(uuid.uuid4()), str(uuid.uuid4())
    assert make_client(actor_id=None).put(
        "/rest-days/2026-08-01", json={"confirmed": True}
    ).status_code == 403
    assert make_client(actor_id="not-a-uuid").put(
        "/rest-days/2026-08-01", json={"confirmed": True}
    ).status_code == 403
    forged = make_client(actor_id=athlete_b).put(
        "/rest-days/2026-08-01",
        json={"confirmed": True, "athlete_id": athlete_a},
    )
    assert forged.status_code == 422
    assert make_client(actor_id=athlete_a).put(
        "/rest-days/2026-08-01", json={"confirmed": True}
    ).status_code == 200
    assert make_client(actor_id=athlete_b).put(
        "/rest-days/2026-08-02", json={"confirmed": True}
    ).status_code == 200
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT athlete_id,date FROM athlete_rest_days ORDER BY date")
        ).all()
    assert [(str(row.athlete_id), str(row.date)) for row in rows] == [
        (athlete_a, "2026-08-01"),
        (athlete_b, "2026-08-02"),
    ]

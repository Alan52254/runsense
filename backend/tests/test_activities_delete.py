"""DB-dependent tests for DELETE /activities/{activity_id}.

This is a soft delete (deleted_at timestamp), not a real row removal -- the
runtime role is deliberately never granted DELETE on completed_activities
(see migration 0001 / 0019). See activities.py's delete_activity docstring.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from conftest import requires_db


def _create_activity(client, **overrides) -> dict:
    payload = {
        "client_mutation_id": str(uuid.uuid4()),
        "duration_minutes": 30,
        "rpe": 5,
        "performed_at": "2026-08-07T09:15:00Z",
        **overrides,
    }
    resp = client.post("/activities", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@requires_db
def test_delete_own_activity_succeeds(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    created = _create_activity(client)

    resp = client.delete(f"/activities/{created['id']}")
    assert resp.status_code == 204
    assert resp.content == b""

    history = client.get("/activities").json()
    assert created["id"] not in [item["id"] for item in history["items"]]


@requires_db
def test_deleted_activity_no_longer_counts_toward_session_load(make_client, new_athlete_id):
    # Same regression this endpoint exists to avoid: a deleted activity must
    # not leave its session_load baked into the materialized load trend --
    # recompute_training_load is the same pull-based re-derivation
    # create_activity already relies on, just triggered from the other
    # direction (an input disappearing, not appearing).
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    created = _create_activity(client, duration_minutes=60, rpe=8)  # 480 AU

    before = client.get("/training-load/trend?end_date=2026-08-07").json()
    assert before["series"][0]["points"][-1]["acute_load"] == 480

    client.delete(f"/activities/{created['id']}")

    after = client.get("/training-load/trend?end_date=2026-08-07").json()
    assert after["series"][0]["points"][-1]["acute_load"] == 0


@requires_db
def test_delete_someone_elses_activity_is_rejected(make_client, new_athlete_id):
    owner = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    created = _create_activity(owner)

    other_athlete_id = str(uuid.uuid4())
    intruder = make_client(actor_id=other_athlete_id, timezones={other_athlete_id: "Asia/Taipei"})
    resp = intruder.delete(f"/activities/{created['id']}")
    assert resp.status_code == 404
    assert resp.json() == {"error": "ACTIVITY_NOT_FOUND"}

    # The activity survives the rejected attempt from a non-owner. Both
    # clients share one app instance whose actor dependency override is
    # global (see ClientFactory), so re-scope back to the owner before
    # checking rather than reusing the now-stale `owner` handle.
    owner_again = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    history = owner_again.get("/activities").json()
    assert created["id"] in [item["id"] for item in history["items"]]


@requires_db
def test_delete_nonexistent_activity_returns_404(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    resp = client.delete(f"/activities/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json() == {"error": "ACTIVITY_NOT_FOUND"}


@requires_db
def test_delete_is_a_soft_delete_the_row_still_physically_exists(
    make_client, admin_engine, new_athlete_id
):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    created = _create_activity(client)

    client.delete(f"/activities/{created['id']}")

    with admin_engine.connect() as conn:
        row = conn.execute(
            text("SELECT deleted_at FROM completed_activities WHERE id=:id"),
            {"id": created["id"]},
        ).first()
    assert row is not None  # row still physically present
    assert row.deleted_at is not None  # just flagged, not removed


@requires_db
def test_deleting_an_already_deleted_activity_returns_404(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    created = _create_activity(client)

    first = client.delete(f"/activities/{created['id']}")
    assert first.status_code == 204

    second = client.delete(f"/activities/{created['id']}")
    assert second.status_code == 404
    assert second.json() == {"error": "ACTIVITY_NOT_FOUND"}


@requires_db
def test_deleting_an_activity_clears_its_rest_day_conflict(make_client, new_athlete_id):
    # _HAS_ACTIVITY (routes/training_load.py) must also respect deleted_at,
    # or a soft-deleted activity would keep permanently blocking that date
    # from ever being confirmed as a rest day.
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    created = _create_activity(client, performed_at="2026-08-01T10:00:00Z")

    blocked = client.put("/rest-days/2026-08-01", json={"confirmed": True})
    assert blocked.status_code == 409

    client.delete(f"/activities/{created['id']}")

    allowed = client.put("/rest-days/2026-08-01", json={"confirmed": True})
    assert allowed.status_code == 200

"""Completed-activity history interface tests against real PostgreSQL."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.providers import DemoCurrentActorProvider
from app.routes import activities as activities_module
from conftest import _get_connection_as_runtime_role, requires_db

DEMO_SECRET = os.environ.get("DEMO_JWT_SECRET", "test-only-demo-secret-at-least-32-bytes")


def _payload(*, performed_at: str, duration: float = 30, rpe: int = 5) -> dict:
    return {
        "client_mutation_id": str(uuid.uuid4()),
        "duration_minutes": duration,
        "rpe": rpe,
        "performed_at": performed_at,
    }


def _insert_activities(admin_engine, *, athlete_id: str, count: int) -> list[str]:
    ids: list[str] = []
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        activity_id = str(uuid.uuid4())
        ids.append(activity_id)
        rows.append(
            {
                "id": activity_id,
                "athlete_id": athlete_id,
                "cmid": str(uuid.uuid4()),
                "fingerprint": f"history-{activity_id}",
                "performed_at": base + timedelta(hours=index),
                "local_date": (base + timedelta(hours=index)).date(),
            }
        )
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO completed_activities (
                    id, athlete_id, client_mutation_id, request_fingerprint,
                    duration_minutes, rpe, performed_at, timezone_snapshot,
                    local_training_date, session_load
                ) VALUES (
                    :id, :athlete_id, :cmid, :fingerprint,
                    30, 5, :performed_at, 'UTC', :local_date, 150
                )
                """
            ),
            rows,
        )
    return ids


def _demo_history_client() -> TestClient:
    def demo_provider(request: Request) -> DemoCurrentActorProvider:
        return DemoCurrentActorProvider(request, secret=DEMO_SECRET)

    app.dependency_overrides[activities_module.get_current_actor_provider] = demo_provider
    app.dependency_overrides[activities_module.get_connection] = _get_connection_as_runtime_role
    return TestClient(app)


@requires_db
def test_tc_history_001_reads_back_canonical_created_activity(make_client, new_athlete_id):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "Asia/Taipei"})
    created = client.post(
        "/activities",
        json=_payload(performed_at="2026-08-07T16:30:00Z", duration=45, rpe=6),
    )
    assert created.status_code == 201, created.text

    history = client.get("/activities")

    assert history.status_code == 200, history.text
    assert history.json() == {"items": [created.json()], "next_cursor": None}


@requires_db
def test_tc_history_002_empty_history(make_client, new_athlete_id):
    response = make_client(actor_id=new_athlete_id).get("/activities")

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


@requires_db
@pytest.mark.parametrize("actor_id", [None, "not-a-uuid"])
def test_tc_history_003_missing_or_malformed_actor_fails_closed(make_client, actor_id):
    response = make_client(actor_id=actor_id).get("/activities")

    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_tc_history_003_expired_token_fails_closed():
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        DEMO_SECRET,
        algorithm="HS256",
    )
    try:
        response = _demo_history_client().get(
            "/activities",
            headers={"Authorization": f"Bearer {expired}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_tc_history_004_actor_isolation_ignores_forged_identity(
    make_client, admin_engine
):
    athlete_a = str(uuid.uuid4())
    athlete_b = str(uuid.uuid4())
    ids_a = _insert_activities(admin_engine, athlete_id=athlete_a, count=2)
    ids_b = _insert_activities(admin_engine, athlete_id=athlete_b, count=1)
    client_b = make_client(actor_id=athlete_b)

    response = client_b.get(
        "/activities",
        params={"athlete_id": athlete_a},
        headers={"X-User-Id": athlete_a},
    )

    assert response.status_code == 200
    returned_ids = [item["id"] for item in response.json()["items"]]
    assert returned_ids == ids_b
    assert not set(ids_a) & set(returned_ids)


@requires_db
def test_tc_history_005_orders_by_performed_at_then_id_desc(make_client, admin_engine):
    athlete_id = str(uuid.uuid4())
    earlier_id = str(uuid.uuid4())
    same_time_ids = sorted([str(uuid.uuid4()), str(uuid.uuid4())], reverse=True)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO completed_activities (
                    id, athlete_id, client_mutation_id, request_fingerprint,
                    duration_minutes, rpe, performed_at, timezone_snapshot,
                    local_training_date, session_load
                ) VALUES (
                    :id, :athlete_id, :cmid, :fingerprint,
                    30, 5, :performed_at, 'UTC', DATE '2026-08-01', 150
                )
                """
            ),
            [
                {
                    "id": earlier_id,
                    "athlete_id": athlete_id,
                    "cmid": str(uuid.uuid4()),
                    "fingerprint": "earlier",
                    "performed_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                },
                *[
                    {
                        "id": activity_id,
                        "athlete_id": athlete_id,
                        "cmid": str(uuid.uuid4()),
                        "fingerprint": activity_id,
                        "performed_at": datetime(2026, 8, 2, tzinfo=timezone.utc),
                    }
                    for activity_id in same_time_ids
                ],
            ],
        )

    response = make_client(actor_id=athlete_id).get("/activities")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        *same_time_ids,
        earlier_id,
    ]


@requires_db
def test_tc_history_006_page_size_bounds(make_client, admin_engine):
    athlete_id = str(uuid.uuid4())
    _insert_activities(admin_engine, athlete_id=athlete_id, count=101)
    client = make_client(actor_id=athlete_id)

    default_page = client.get("/activities")
    minimum_page = client.get("/activities", params={"limit": 1})
    maximum_page = client.get("/activities", params={"limit": 100})
    below_minimum = client.get("/activities", params={"limit": 0})
    above_maximum = client.get("/activities", params={"limit": 101})

    assert default_page.status_code == 200
    assert len(default_page.json()["items"]) == 20
    assert default_page.json()["next_cursor"] is not None
    assert len(minimum_page.json()["items"]) == 1
    assert len(maximum_page.json()["items"]) == 100
    assert below_minimum.status_code == 422
    assert above_maximum.status_code == 422


@requires_db
def test_tc_history_007_cursor_traversal_returns_each_row_once(
    make_client, admin_engine
):
    athlete_id = str(uuid.uuid4())
    expected_ids = set(_insert_activities(admin_engine, athlete_id=athlete_id, count=7))
    client = make_client(actor_id=athlete_id)
    seen: list[str] = []
    cursor = None

    while True:
        params = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/activities", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 7
    assert set(seen) == expected_ids


@requires_db
@pytest.mark.parametrize("cursor", ["not*base64", "e30", "eyJ2IjoyfQ"])
def test_tc_history_008_malformed_cursor_returns_422(make_client, new_athlete_id, cursor):
    response = make_client(actor_id=new_athlete_id).get(
        "/activities", params={"cursor": cursor}
    )

    assert response.status_code == 422
    assert "items" not in response.json()


@requires_db
def test_tc_history_009_newer_insert_does_not_shift_remaining_pages(
    make_client, admin_engine
):
    athlete_id = str(uuid.uuid4())
    preexisting_ids = set(_insert_activities(admin_engine, athlete_id=athlete_id, count=5))
    client = make_client(actor_id=athlete_id)
    first = client.get("/activities", params={"limit": 2})
    assert first.status_code == 200
    first_body = first.json()
    first_ids = [item["id"] for item in first_body["items"]]

    with admin_engine.begin() as conn:
        newer_id = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO completed_activities (
                    id, athlete_id, client_mutation_id, request_fingerprint,
                    duration_minutes, rpe, performed_at, timezone_snapshot,
                    local_training_date, session_load
                ) VALUES (
                    :id, :athlete_id, :cmid, 'newer-between-pages',
                    30, 5, TIMESTAMPTZ '2026-09-01T00:00:00Z', 'UTC',
                    DATE '2026-09-01', 150
                )
                """
            ),
            {"id": newer_id, "athlete_id": athlete_id, "cmid": str(uuid.uuid4())},
        )

    remaining: list[str] = []
    cursor = first_body["next_cursor"]
    while cursor is not None:
        page = client.get("/activities", params={"limit": 2, "cursor": cursor})
        assert page.status_code == 200, page.text
        body = page.json()
        remaining.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]

    traversed = first_ids + remaining
    assert len(traversed) == len(set(traversed)) == 5
    assert set(traversed) == preexisting_ids
    assert newer_id not in traversed

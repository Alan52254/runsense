"""DB-dependent tests for Settings -- Security/Privacy/Integration
(docs/mvp-checklist.md, pulled back into scope from "Deferred past MVP").
See backend/app/routes/settings.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.main import app
from app.providers import StaticCurrentSessionProvider
from app.routes import settings as settings_module

from conftest import requires_db


def _insert_user(admin_engine, user_id) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": user_id, "email": f"{user_id}@example.test"},
        )


def _insert_session(admin_engine, session_id, user_id, *, device="Chrome on macOS") -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth_sessions (id, user_id, device, ip_masked, location) "
                "VALUES (:id, :user_id, :device, '203.0.113.xxx', 'Taipei, TW')"
            ),
            {"id": session_id, "user_id": user_id, "device": device},
        )


def _override_session_provider(session_id: str | None) -> None:
    app.dependency_overrides[settings_module.get_current_session_provider] = (
        lambda: StaticCurrentSessionProvider(session_id)
    )


@requires_db
def test_list_sessions_marks_current_session(make_client, admin_engine):
    user_id = uuid.uuid4()
    current = uuid.uuid4()
    other = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    _insert_session(admin_engine, current, user_id, device="Current device")
    _insert_session(admin_engine, other, user_id, device="Other device")

    client = make_client(actor_id=str(user_id))
    _override_session_provider(str(current))
    try:
        response = client.get("/me/settings/sessions")
    finally:
        app.dependency_overrides.pop(settings_module.get_current_session_provider, None)

    assert response.status_code == 200, response.text
    items = {row["id"]: row for row in response.json()["items"]}
    assert items[str(current)]["is_current"] is True
    assert items[str(other)]["is_current"] is False


@requires_db
def test_list_sessions_only_returns_actors_own_sessions(make_client, admin_engine):
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    _insert_user(admin_engine, other_user_id)
    _insert_session(admin_engine, mine, user_id)
    _insert_session(admin_engine, theirs, other_user_id)

    client = make_client(actor_id=str(user_id))
    response = client.get("/me/settings/sessions")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["items"]}
    assert ids == {str(mine)}


@requires_db
def test_revoke_session_removes_it_from_the_list(make_client, admin_engine):
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    _insert_session(admin_engine, session_id, user_id)

    client = make_client(actor_id=str(user_id))
    revoke = client.delete(f"/me/settings/sessions/{session_id}")
    assert revoke.status_code == 204

    listing = client.get("/me/settings/sessions")
    assert listing.json()["items"] == []


@requires_db
def test_revoke_someone_elses_session_is_rejected(make_client, admin_engine):
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    their_session = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    _insert_user(admin_engine, other_user_id)
    _insert_session(admin_engine, their_session, other_user_id)

    client = make_client(actor_id=str(user_id))
    response = client.delete(f"/me/settings/sessions/{their_session}")
    assert response.status_code == 404
    assert response.json() == {"error": "SESSION_NOT_FOUND"}


@requires_db
def test_revoking_the_current_session_is_allowed(make_client, admin_engine):
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    _insert_session(admin_engine, session_id, user_id)

    client = make_client(actor_id=str(user_id))
    _override_session_provider(str(session_id))
    try:
        response = client.delete(f"/me/settings/sessions/{session_id}")
    finally:
        app.dependency_overrides.pop(settings_module.get_current_session_provider, None)
    assert response.status_code == 204


@requires_db
def test_mfa_verify_rejects_wrong_code(make_client, admin_engine):
    user_id = uuid.uuid4()
    _insert_user(admin_engine, user_id)

    client = make_client(actor_id=str(user_id))
    response = client.post("/me/settings/mfa/verify", json={"code": "000000"})
    assert response.status_code == 422
    assert response.json() == {"error": "INVALID_MFA_CODE"}


@requires_db
def test_mfa_verify_accepts_the_fixed_demo_code_and_marks_the_session(make_client, admin_engine):
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    _insert_session(admin_engine, session_id, user_id)

    client = make_client(actor_id=str(user_id))
    _override_session_provider(str(session_id))
    try:
        response = client.post("/me/settings/mfa/verify", json={"code": "424242"})
    finally:
        app.dependency_overrides.pop(settings_module.get_current_session_provider, None)

    assert response.status_code == 200, response.text
    assert response.json() == {"mfa_satisfied": True}

    with admin_engine.begin() as conn:
        row = conn.execute(
            text("SELECT mfa_satisfied FROM auth_sessions WHERE id = :id"), {"id": session_id}
        ).first()
    assert row.mfa_satisfied is True


@requires_db
def test_privacy_export_includes_own_activities_and_training_load_and_writes_audit_entry(
    make_client, admin_engine
):
    user_id = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:id, 'Asia/Taipei')"),
            {"id": user_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO completed_activities (
                    athlete_id, client_mutation_id, request_fingerprint,
                    duration_minutes, rpe, performed_at, timezone_snapshot,
                    local_training_date, session_load
                ) VALUES (
                    :athlete_id, :cmid, 'fp-1', 30, 5, :performed_at, 'Asia/Taipei',
                    :local_date, 150
                )
                """
            ),
            {
                "athlete_id": user_id,
                "cmid": uuid.uuid4(),
                "performed_at": datetime.now(timezone.utc),
                "local_date": datetime.now(timezone.utc).date(),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO training_load_daily (
                    athlete_id, date, unit, session_load, source_metric,
                    acute_load, chronic_load, load_ratio, data_quality,
                    observation_days, algorithm_version, schema_version,
                    computed_at, input_snapshot_hash
                ) VALUES (
                    :athlete_id, :date, 'AU', 150, 'SESSION_RPE',
                    150, 37.5, 4.0, 'INSUFFICIENT',
                    1, 'tl-v1', 1, :computed_at, :hash
                )
                """
            ),
            {
                "athlete_id": user_id,
                "date": datetime.now(timezone.utc).date(),
                "computed_at": datetime.now(timezone.utc),
                "hash": "a" * 64,
            },
        )

    client = make_client(actor_id=str(user_id))
    response = client.get("/me/settings/privacy/export")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"]["timezone"] == "Asia/Taipei"
    assert len(body["completed_activities"]) == 1
    assert len(body["training_load_daily"]) == 1

    audit = client.get("/me/settings/audit-log")
    events = [row["event"] for row in audit.json()["items"]]
    assert "DATA_EXPORT" in events


@requires_db
def test_deletion_request_sets_timestamp_and_is_idempotent_to_call_twice(make_client, admin_engine):
    user_id = uuid.uuid4()
    _insert_user(admin_engine, user_id)

    client = make_client(actor_id=str(user_id))
    first = client.post("/me/settings/privacy/deletion-request")
    assert first.status_code == 200, first.text
    assert first.json()["deletion_requested_at"] is not None

    second = client.post("/me/settings/privacy/deletion-request")
    assert second.status_code == 200


@requires_db
def test_garmin_integration_flag_defaults_to_disabled(make_client, admin_engine):
    user_id = uuid.uuid4()
    _insert_user(admin_engine, user_id)
    assert os.environ.get("GARMIN_ACTIVITY_SYNC_ENABLED", "").lower() != "true"

    client = make_client(actor_id=str(user_id))
    response = client.get("/me/settings/integrations/garmin")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert "GARMIN_ACTIVITY_SYNC_ENABLED" in body["reason"]


@requires_db
def test_garmin_integration_status_requires_an_authenticated_actor(make_client):
    response = make_client(actor_id=None).get("/me/settings/integrations/garmin")

    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_settings_endpoints_reject_missing_actor_context(make_client):
    client = make_client(actor_id=None)
    assert client.get("/me/settings/sessions").status_code == 403
    assert client.get("/me/settings/privacy/export").status_code == 403
    assert client.post("/me/settings/privacy/deletion-request").status_code == 403

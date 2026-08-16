"""Competition demo identity integration tests against real PostgreSQL."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.routes import activities as activities_module
from conftest import _get_connection_as_runtime_role, requires_db

DEMO_SECRET = os.environ.get("DEMO_JWT_SECRET", "test-only-demo-secret")


def _insert_demo_user(admin_engine, *, email: str, password: str, timezone_name: str):
    user_id = uuid.uuid4()
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :hash)"),
            {"id": user_id, "email": email, "hash": password_hash},
        )
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:id, :timezone)"),
            {"id": user_id, "timezone": timezone_name},
        )
    return user_id


def _demo_client() -> TestClient:
    app.dependency_overrides[activities_module.get_connection] = _get_connection_as_runtime_role
    return TestClient(app)


@requires_db
def test_tc_demo_auth_001_correct_credentials_issue_decodable_token(admin_engine):
    user_id = _insert_demo_user(
        admin_engine,
        email="correct@runsense.demo",
        password="CorrectDemo!2026",
        timezone_name="Asia/Taipei",
    )
    response = _demo_client().post(
        "/auth/demo-login",
        json={"email": "correct@runsense.demo", "password": "CorrectDemo!2026"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    claims = jwt.decode(body["access_token"], DEMO_SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(user_id)
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(timezone.utc)


@requires_db
def test_tc_demo_auth_002_and_003_invalid_credentials_are_identical(admin_engine):
    _insert_demo_user(
        admin_engine,
        email="known@runsense.demo",
        password="KnownDemo!2026",
        timezone_name="Asia/Taipei",
    )
    client = _demo_client()
    wrong = client.post(
        "/auth/demo-login",
        json={"email": "known@runsense.demo", "password": "wrong"},
    )
    unknown = client.post(
        "/auth/demo-login",
        json={"email": "unknown@runsense.demo", "password": "wrong"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"error": "INVALID_CREDENTIALS"}
    assert "access_token" not in wrong.json()
    assert "access_token" not in unknown.json()


@requires_db
def test_invalid_overlong_password_is_rejected_identically_for_known_and_unknown_email(
    admin_engine,
):
    _insert_demo_user(
        admin_engine,
        email="known-long-password@runsense.demo",
        password="KnownDemo!2026",
        timezone_name="Asia/Taipei",
    )
    client = _demo_client()
    overlong_password = "x" * 73

    known = client.post(
        "/auth/demo-login",
        json={
            "email": "known-long-password@runsense.demo",
            "password": overlong_password,
        },
    )
    unknown = client.post(
        "/auth/demo-login",
        json={"email": "unknown@runsense.demo", "password": overlong_password},
    )

    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json() == {"error": "INVALID_CREDENTIALS"}


def test_tc_demo_auth_004_flag_absent_route_is_404_and_defaults_fail_loudly():
    script = """
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app, raise_server_exceptions=False)
login = client.post('/auth/demo-login', json={'email':'x','password':'y'})
activity = client.post('/activities', json={
  'client_mutation_id':'00000000-0000-0000-0000-000000000001',
  'duration_minutes':1, 'rpe':1, 'performed_at':'2026-08-07T09:15:00Z'})
print(login.status_code, activity.status_code)
"""
    for flag_value in (None, "false"):
        env = os.environ.copy()
        if flag_value is None:
            env.pop("COMPETITION_DEMO_ONLY", None)
        else:
            env["COMPETITION_DEMO_ONLY"] = flag_value
        env.pop("DEMO_JWT_SECRET", None)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "404 500"


@requires_db
def test_tc_demo_auth_005_expired_and_malformed_tokens_fail_closed():
    client = _demo_client()
    payload = {
        "client_mutation_id": str(uuid.uuid4()),
        "duration_minutes": 30,
        "rpe": 5,
        "performed_at": "2026-08-07T16:30:00Z",
    }
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        DEMO_SECRET,
        algorithm="HS256",
    )
    for token in (expired, "not-a-jwt"):
        response = client.post(
            "/activities", json=payload, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert response.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
def test_tc_demo_auth_006_token_claim_wins_over_identity_header(admin_engine):
    token_user = _insert_demo_user(
        admin_engine,
        email="token@runsense.demo",
        password="TokenDemo!2026",
        timezone_name="Asia/Taipei",
    )
    forged_user = uuid.uuid4()
    token = jwt.encode(
        {"sub": str(token_user), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        DEMO_SECRET,
        algorithm="HS256",
    )
    response = _demo_client().post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 30,
            "rpe": 5,
            "performed_at": "2026-08-07T16:30:00Z",
        },
        headers={"Authorization": f"Bearer {token}", "X-User-Id": str(forged_user)},
    )
    assert response.status_code == 201, response.text
    assert response.json()["athlete_id"] == str(token_user)


@requires_db
def test_tc_tz_demo_001_db_profile_timezone_drives_existing_create_logic(admin_engine):
    user_id = _insert_demo_user(
        admin_engine,
        email="timezone@runsense.demo",
        password="TimezoneDemo!2026",
        timezone_name="Asia/Taipei",
    )
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        DEMO_SECRET,
        algorithm="HS256",
    )
    response = _demo_client().post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 30,
            "rpe": 5,
            "performed_at": "2026-08-07T16:30:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["local_training_date"] == "2026-08-08"
    assert response.json()["timezone_snapshot"] == "Asia/Taipei"


@requires_db
def test_tc_schema_demo_identity_tables_have_no_team_id(admin_engine):
    with admin_engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN ('users', 'athlete_profiles')"
            )
        ).all()
    assert all(column_name != "team_id" for _, column_name in columns)
    assert {table_name for table_name, _ in columns} == {"users", "athlete_profiles"}

"""Shared opaque-box E2E fixtures, synthetic FIT/GDPR builders, and DB/ASGI harnesses."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import struct
import sys
import uuid
import xml.etree.ElementTree as ET
import zlib

import bcrypt
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
import httpx
import jwt
import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

_TESTS_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _TESTS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import conftest as root_conftest  # noqa: E402

from app.clock import Clock, SystemClock  # noqa: E402
from app.main import app  # noqa: E402
from app.safety_triage import SafetyTriageInput  # noqa: E402
from app.providers import (  # noqa: E402
    CurrentActorProvider,
    DbProfileTimezoneProvider,
    DemoCurrentActorProvider,
    DemoCurrentSessionProvider,
    InMemoryProfileTimezoneProvider,
    ProfileTimezoneProvider,
    StaticCurrentActorProvider,
)
from app.routes import activities as activities_module  # noqa: E402
from app.routes import chat as chat_module  # noqa: E402
from app.routes import guidance as guidance_module  # noqa: E402
from app.routes import settings as settings_module  # noqa: E402
from app.routes import training_load as training_load_module  # noqa: E402
from app.routes import training_plan as training_plan_module  # noqa: E402

requires_db = root_conftest.requires_db
_db_available = root_conftest._db_available
_get_connection_as_runtime_role = root_conftest._get_connection_as_runtime_role

E2E_DEMO_SECRET = os.environ.get("DEMO_JWT_SECRET", "e2e-test-only-demo-secret-32bytes!")


def pytest_configure(config: pytest.Config) -> None:
    """Register E2E custom markers without modifying backend/pyproject.toml."""
    markers = [
        "e2e: Opaque-box E2E tests across RunSence requirements R1-R5",
        "e2e_db: E2E tests requiring isolated PostgreSQL 16 + runsense_runtime forced RLS",
        "e2e_tier1: Tier 1 isolated happy-path feature verification (F1-F9)",
        "e2e_tier2: Tier 2 boundary, negative, fallback, and security verification (F1-F9)",
        "e2e_tier3: Tier 3 pairwise cross-feature combination tests",
        "e2e_tier4: Tier 4 multi-step end-to-end user journeys",
        "e2e_slow: Slow E2E tests (XGBoost training or subprocess isolation)",
    ]
    for marker in markers:
        config.addinivalue_line("markers", marker)


class FixedClock(Clock):
    """Deterministic UTC clock for E2E date/time tests."""

    def __init__(self, fixed_utc: datetime) -> None:
        if fixed_utc.tzinfo is None:
            fixed_utc = fixed_utc.replace(tzinfo=timezone.utc)
        self._fixed = fixed_utc.astimezone(timezone.utc)

    def now_utc(self) -> datetime:
        return self._fixed


@pytest.fixture()
def no_external_apis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear external paid/network API keys so local fallbacks are deterministically exercised."""
    for env_key in (
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "OPENWEATHER_API_KEY",
        "RUNSENCE_MEDIA_API_KEY",
        "RUNSENCE_MEDIA_API_URL",
        "GUIDANCE_PROVIDER",
    ):
        monkeypatch.delenv(env_key, raising=False)


@pytest.fixture()
def restore_app_overrides() -> Iterator[None]:
    """Snapshot and cleanly restore FastAPI dependency_overrides around every test."""
    snapshot = dict(app.dependency_overrides)
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(snapshot)


class _NoDbConnectionSentinel:
    """Fast-fail sentinel yielded by make_no_db_client so Pydantic 422 checks never block on TCP."""

    def begin(self):  # pragma: no cover - only reached if a no-DB test hits SQL
        raise RuntimeError("make_no_db_client does not provide a PostgreSQL connection")

    def execute(self, *args, **kwargs):  # pragma: no cover
        raise RuntimeError("make_no_db_client does not provide a PostgreSQL connection")


def _no_db_connection() -> Iterator[_NoDbConnectionSentinel]:
    yield _NoDbConnectionSentinel()


@pytest.fixture()
def make_no_db_client(
    no_external_apis: None, restore_app_overrides: None
) -> Callable[..., TestClient]:
    """Build an ASGI TestClient for routes that do not require PostgreSQL.

    Each returned TestClient carries a unique X-E2E-Client header so creating
    multiple actors within the same test never overwrites prior clients.
    """
    clients: dict[str, tuple[str | None, Clock | None]] = {}

    def _actor_provider(request: Request) -> CurrentActorProvider:
        key = request.headers.get("X-E2E-Client")
        actor_id = clients[key][0] if key and key in clients else None
        return StaticCurrentActorProvider(actor_id)

    def _clock_provider(request: Request) -> Clock:
        key = request.headers.get("X-E2E-Client")
        fixed = clients[key][1] if key and key in clients else None
        return fixed if fixed is not None else SystemClock()

    app.dependency_overrides[activities_module.get_current_actor_provider] = _actor_provider
    app.dependency_overrides[activities_module.get_connection] = _no_db_connection
    app.dependency_overrides[training_load_module.get_clock] = _clock_provider
    app.dependency_overrides[guidance_module.get_clock] = _clock_provider
    app.dependency_overrides[training_plan_module.get_clock] = _clock_provider
    app.dependency_overrides[chat_module.get_clock] = _clock_provider

    def _factory(
        *,
        actor_id: str | None = None,
        clock_utc: datetime | None = None,
        raise_server_exceptions: bool = True,
    ) -> TestClient:
        client_key = str(uuid.uuid4())
        clients[client_key] = (
            actor_id,
            FixedClock(clock_utc) if clock_utc is not None else None,
        )
        return TestClient(
            app,
            raise_server_exceptions=raise_server_exceptions,
            headers={"X-E2E-Client": client_key},
        )

    return _factory


@pytest.fixture()
def e2e_async_client(no_external_apis: None, restore_app_overrides: None):
    """Factory returning an httpx.AsyncClient bound directly to FastAPI ASGITransport."""
    clients: dict[str, str | None] = {}

    def _actor_provider(request: Request) -> CurrentActorProvider:
        key = request.headers.get("X-E2E-Client")
        actor_id = clients[key] if key and key in clients else None
        return StaticCurrentActorProvider(actor_id)

    app.dependency_overrides[activities_module.get_current_actor_provider] = _actor_provider
    app.dependency_overrides[activities_module.get_connection] = _no_db_connection

    def _factory(*, actor_id: str | None = None) -> httpx.AsyncClient:
        client_key = str(uuid.uuid4())
        clients[client_key] = actor_id
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-E2E-Client": client_key},
        )

    return _factory


@pytest.fixture()
def e2e_db_cleanup(request: pytest.FixtureRequest) -> Iterator[None]:
    """Clean M3 tables (e.g. athlete_wellness_daily) if present alongside root cleanup."""
    yield
    if not _db_available():
        return
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        return
    engine = create_engine(test_url, future=True)
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'athlete_wellness_daily'"
                )
            ).first()
            if exists is not None:
                conn.execute(text("TRUNCATE TABLE athlete_wellness_daily CASCADE"))
    finally:
        engine.dispose()


@pytest.fixture()
def make_e2e_db_client(
    no_external_apis: None,
    restore_app_overrides: None,
    e2e_db_cleanup: None,
) -> Callable[..., TestClient]:
    """Build an ASGI TestClient backed by TEST_DATABASE_URL + runsense_runtime RLS.

    Each returned TestClient carries a unique X-E2E-Client header so multi-actor
    tests (owner + other, coach + athlete, outsider + coach) never overwrite each other.
    """
    clients: dict[str, tuple[str | None, dict[str, str], Clock | None]] = {}

    def _actor_provider(request: Request) -> CurrentActorProvider:
        key = request.headers.get("X-E2E-Client")
        actor_id = clients[key][0] if key and key in clients else None
        return StaticCurrentActorProvider(actor_id)

    def _timezone_provider(request: Request) -> ProfileTimezoneProvider:
        key = request.headers.get("X-E2E-Client")
        tz_map = clients[key][1] if key and key in clients else {}
        return InMemoryProfileTimezoneProvider(tz_map)

    def _clock_provider(request: Request) -> Clock:
        key = request.headers.get("X-E2E-Client")
        fixed = clients[key][2] if key and key in clients else None
        return fixed if fixed is not None else SystemClock()

    app.dependency_overrides[activities_module.get_current_actor_provider] = _actor_provider
    app.dependency_overrides[activities_module.get_profile_timezone_provider] = _timezone_provider
    app.dependency_overrides[activities_module.get_connection] = _get_connection_as_runtime_role
    app.dependency_overrides[training_load_module.get_clock] = _clock_provider
    app.dependency_overrides[guidance_module.get_clock] = _clock_provider
    app.dependency_overrides[training_plan_module.get_clock] = _clock_provider
    app.dependency_overrides[chat_module.get_clock] = _clock_provider

    def _factory(
        *,
        actor_id: str | None,
        timezones: dict[str, str] | None = None,
        clock_utc: datetime | None = None,
        raise_server_exceptions: bool = True,
    ) -> TestClient:
        client_key = str(uuid.uuid4())
        clients[client_key] = (
            actor_id,
            dict(timezones or {}),
            FixedClock(clock_utc) if clock_utc is not None else None,
        )
        return TestClient(
            app,
            raise_server_exceptions=raise_server_exceptions,
            headers={"X-E2E-Client": client_key},
        )

    return _factory


@pytest.fixture()
def patch_chat_test_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine | None]:
    """Ensure @AI background task (POST /chat/rooms/{id}/messages) uses TEST_DATABASE_URL."""
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url or not _db_available():
        yield None
        return
    engine = create_engine(test_url, future=True)
    import app.db as db_module
    import app.routes.chat as chat_routes_module

    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    monkeypatch.setattr(chat_routes_module, "get_engine", lambda: engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def make_e2e_demo_client(
    monkeypatch: pytest.MonkeyPatch,
    no_external_apis: None,
    e2e_db_cleanup: None,
) -> Callable[..., TestClient]:
    """Build a real JWT + auth_sessions + MFA TestClient without mutating module globals."""
    from app.routes.demo_auth import router as demo_auth_router
    from app.routes import activities as act_mod
    from fastapi import Depends
    from sqlalchemy import Connection

    def _factory(*, clock_utc: datetime | None = None) -> TestClient:
        monkeypatch.setenv("DEMO_JWT_SECRET", E2E_DEMO_SECRET)
        monkeypatch.setattr(settings_module, "_competition_demo_only", True)
        monkeypatch.setattr(act_mod, "_competition_demo_only", True)

        demo_app = FastAPI(title="RunSense E2E Demo Harness")
        for router in (
            demo_auth_router,
            act_mod.router,
            training_load_module.router,
            guidance_module.router,
            settings_module.router,
        ):
            demo_app.include_router(router)

        # Include remaining routers from app.main without duplicating routes
        from app.routes import (
            assignments,
            chat,
            garmin,
            health,
            health_media,
            injury_guidance,
            injury_reports,
            me,
            profile,
            teams,
            training_plan,
            weather,
            workout_analysis,
        )

        for router in (
            training_plan.router,
            profile.router,
            weather.router,
            health_media.router,
            garmin.router,
            teams.router,
            me.router,
            injury_reports.router,
            injury_guidance.router,
            assignments.router,
            workout_analysis.router,
            chat.router,
            health.router,
        ):
            demo_app.include_router(router)

        # Copy exception handlers from main app
        for exc_cls, handler in app.exception_handlers.items():
            demo_app.add_exception_handler(exc_cls, handler)

        def _demo_actor(
            request: Request,
            conn: Connection = Depends(act_mod.get_connection),
        ) -> DemoCurrentActorProvider:
            return DemoCurrentActorProvider(request, conn, secret=E2E_DEMO_SECRET)

        def _demo_session(request: Request) -> DemoCurrentSessionProvider:
            return DemoCurrentSessionProvider(request, secret=E2E_DEMO_SECRET)

        def _db_tz(
            conn: Connection = Depends(act_mod.get_connection),
        ) -> DbProfileTimezoneProvider:
            return DbProfileTimezoneProvider(conn)

        demo_app.dependency_overrides[act_mod.get_connection] = _get_connection_as_runtime_role
        demo_app.dependency_overrides[act_mod.get_current_actor_provider] = _demo_actor
        demo_app.dependency_overrides[settings_module.get_current_session_provider] = _demo_session
        demo_app.dependency_overrides[act_mod.get_profile_timezone_provider] = _db_tz
        if clock_utc is not None:
            fixed = FixedClock(clock_utc)
            demo_app.dependency_overrides[training_load_module.get_clock] = lambda: fixed
            demo_app.dependency_overrides[guidance_module.get_clock] = lambda: fixed
            demo_app.dependency_overrides[training_plan_module.get_clock] = lambda: fixed
            demo_app.dependency_overrides[chat_module.get_clock] = lambda: fixed

        return TestClient(demo_app)

    return _factory


# ---------------------------------------------------------------------------
# DB seed helpers for @requires_db tests
# ---------------------------------------------------------------------------


def seed_user(
    admin_engine: Engine,
    *,
    email: str | None = None,
    password: str = "RunSenceE2E!2026",
    display_name: str = "E2E Runner",
    timezone_name: str | None = "Asia/Taipei",
    city: str | None = None,
    sex: str | None = None,
) -> uuid.UUID:
    user_id = uuid.uuid4()
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:id, :email, :pw, :dn)"
            ),
            {
                "id": user_id,
                "email": email or f"runner-{user_id}@runsense.e2e.test",
                "pw": pw_hash,
                "dn": display_name,
            },
        )
        if timezone_name is not None or city is not None or sex is not None:
            conn.execute(
                text(
                    "INSERT INTO athlete_profiles (user_id, timezone, city, sex) "
                    "VALUES (:id, :tz, :city, :sex)"
                ),
                {
                    "id": user_id,
                    "tz": timezone_name or "",
                    "city": city,
                    "sex": sex,
                },
            )
    return user_id


def seed_team_and_members(
    admin_engine: Engine,
    *,
    coach_id: uuid.UUID,
    athlete_id: uuid.UUID,
    athlete_status: str = "ACTIVE",
    consent_scopes: tuple[str, ...] = (),
    team_name: str = "E2E Track Club",
) -> uuid.UUID:
    team_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO teams (id, name) VALUES (:id, :name)"),
            {"id": team_id, "name": team_name},
        )
        conn.execute(
            text(
                "INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) "
                "VALUES (:t, :u, 'coach', 'ACTIVE', now())"
            ),
            {"t": team_id, "u": coach_id},
        )
        if athlete_status == "ACTIVE":
            conn.execute(
                text(
                    "INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) "
                    "VALUES (:t, :u, 'athlete', 'ACTIVE', now())"
                ),
                {"t": team_id, "u": athlete_id},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO team_memberships (team_id, user_id, role, status) "
                    "VALUES (:t, :u, 'athlete', :status)"
                ),
                {"t": team_id, "u": athlete_id, "status": athlete_status},
            )
        for scope in consent_scopes:
            conn.execute(
                text(
                    "INSERT INTO consent_grants (team_id, athlete_id, scope, granted) "
                    "VALUES (:t, :a, :s, true) "
                    "ON CONFLICT (team_id, athlete_id, scope) DO UPDATE SET granted=true"
                ),
                {"t": team_id, "a": athlete_id, "s": scope},
            )
    return team_id


def encode_demo_jwt(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    expires_delta: timedelta = timedelta(hours=1),
    secret: str = E2E_DEMO_SECRET,
) -> str:
    claims: dict[str, object] = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    if session_id is not None:
        claims["sid"] = str(session_id)
    return jwt.encode(claims, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Synthetic De-Identified Binary .FIT & Garmin GDPR JSON Fixtures (Zero PII)
# ---------------------------------------------------------------------------


def _fit_crc16(data: bytes) -> int:
    crc_table = (
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
    )
    crc = 0
    for byte in data:
        tmp = crc_table[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ crc_table[byte & 0xF]
        tmp = crc_table[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ crc_table[(byte >> 4) & 0xF]
    return crc


def _fit_def(local_id: int, global_num: int, fields: list[tuple[int, int, int]]) -> bytes:
    header = 0x40 | (local_id & 0x0F)
    body = bytearray(struct.pack("<BBHB", 0, 0, global_num, len(fields)))
    for field_num, size, base_type in fields:
        body.extend(struct.pack("<BBB", field_num, size, base_type))
    return bytes([header]) + bytes(body)


def build_synthetic_fit_bytes(
    *,
    duration_seconds: int = 120,
    base_hr: int = 148,
    max_hr: int = 166,
    resting_hr: int = 52,
    speed_mm_s: int = 3333,
    device_max_hr: int = 192,
    workout_rpe: int = 70,
    include_zones: bool = True,
) -> bytes:
    """Build deterministic, PII-free binary Garmin FIT bytes parseable by fit_telemetry.parse_fit()."""
    fit_epoch_start = 1164326400  # 2026-11-23T00:00:00Z in FIT seconds
    records = bytearray()

    # 0: file_id (global 0)
    records.extend(_fit_def(0, 0, [(0, 1, 0), (1, 2, 132), (2, 2, 132)]))
    records.extend(struct.pack("<BBHH", 0, 4, 1, 4432))  # activity, garmin, fr165

    if include_zones:
        # 4: zones_target (global 7): max_heart_rate(1,1,2), threshold_hr(2,1,2), hr_calc_type(5,1,0)
        records.extend(_fit_def(4, 7, [(1, 1, 2), (2, 1, 2), (5, 1, 0)]))
        records.extend(struct.pack("<BBBB", 4, device_max_hr, max(120, device_max_hr - 18), 1))
        # 5: user_profile (global 3): resting_heart_rate(8,1,2)
        records.extend(_fit_def(5, 3, [(8, 1, 2)]))
        records.extend(struct.pack("<BB", 5, resting_hr))

    # 1: record (global 20)
    records.extend(
        _fit_def(1, 20, [(253, 4, 134), (3, 1, 2), (4, 1, 2), (5, 4, 134), (73, 4, 134)])
    )
    for sec in range(duration_seconds):
        hr_val = min(max_hr, base_hr + (sec % 12))
        dist_cm = int(sec * speed_mm_s / 10)
        records.extend(struct.pack("<BIBBII", 1, fit_epoch_start + sec, hr_val, 86, dist_cm, speed_mm_s))

    total_dist_cm = int(duration_seconds * speed_mm_s / 10)
    elapsed_ms = duration_seconds * 1000
    # 2: lap (global 19)
    records.extend(
        _fit_def(
            2,
            19,
            [(253, 4, 134), (2, 4, 134), (7, 4, 134), (8, 4, 134), (9, 4, 134), (15, 1, 2), (16, 1, 2)],
        )
    )
    records.extend(
        struct.pack(
            "<BIIIIIBB",
            2,
            fit_epoch_start + duration_seconds,
            fit_epoch_start,
            elapsed_ms,
            elapsed_ms,
            total_dist_cm,
            base_hr + 4,
            max_hr,
        )
    )

    # 3: session (global 18)
    records.extend(
        _fit_def(
            3,
            18,
            [
                (253, 4, 134),
                (2, 4, 134),
                (5, 1, 0),
                (6, 1, 0),
                (7, 4, 134),
                (8, 4, 134),
                (9, 4, 134),
                (16, 1, 2),
                (17, 1, 2),
                (193, 1, 2),
            ],
        )
    )
    records.extend(
        struct.pack(
            "<BIIBBIIIBBB",
            3,
            fit_epoch_start + duration_seconds,
            fit_epoch_start,
            1,
            0,
            elapsed_ms,
            elapsed_ms,
            total_dist_cm,
            base_hr + 4,
            max_hr,
            workout_rpe,
        )
    )

    hdr_wo_crc = struct.pack("<BBHI4s", 14, 0x20, 2111, len(records), b".FIT")
    hdr = hdr_wo_crc + struct.pack("<H", _fit_crc16(hdr_wo_crc))
    body = hdr + bytes(records)
    return body + struct.pack("<H", _fit_crc16(body))


def build_synthetic_garmin_gdpr_bundle(
    *,
    start_date: date = date(2026, 11, 10),
    days: int = 10,
) -> dict[str, object]:
    """Build de-identified synthetic Garmin GDPR UDSFile + sleepData + summarizedActivities."""
    uds_rows: list[dict[str, object]] = []
    sleep_rows: list[dict[str, object]] = []
    activities: list[dict[str, object]] = []
    for idx in range(days):
        d = start_date + timedelta(days=idx)
        iso = d.isoformat()
        uds_rows.append(
            {
                "calendarDate": iso,
                "restingHeartRate": 50 + (idx % 4),
                "minHeartRate": 47,
                "maxHeartRate": 172,
                "bodyBattery": {"chargedValue": 68, "drainedValue": 52},
                "allDayStress": {"aggregatorList": [{"type": "TOTAL", "averageStressLevel": 24 + (idx % 6)}]},
                "totalSteps": 9200 + idx * 150,
            }
        )
        sleep_rows.append(
            {
                "calendarDate": iso,
                "deepSleepSeconds": 5400,
                "lightSleepSeconds": 16200,
                "remSleepSeconds": 5400,
                "awakeSleepSeconds": 600,
                "sleepScores": {"overall": {"value": 82}},
            }
        )
        if idx % 2 == 0:
            ts_ms = int(datetime(d.year, d.month, d.day, 6, 30, tzinfo=timezone.utc).timestamp() * 1000)
            activities.append(
                {
                    "activityId": 900000 + idx,
                    "activityType": "running",
                    "beginTimestamp": ts_ms,
                    "duration": 2400 * 1000,
                    "distance": 750000,  # cm -> 7.5 km
                    "avgHr": 149,
                    "maxHr": 168,
                    "workoutRpe": 60,
                    "vO2MaxValue": 51.0,
                    "aerobicTrainingEffect": 3.2,
                }
            )
    return {
        "uds": uds_rows,
        "sleep": sleep_rows,
        "summarized_activities": {"summarizedActivitiesExport": activities},
    }


# ---------------------------------------------------------------------------
# Media & SSE validation helpers (no PIL / matplotlib)
# ---------------------------------------------------------------------------


def assert_valid_png(raw: bytes) -> tuple[int, int]:
    """Validate PNG magic header, CRC32 chunks, and return (width, height) from IHDR."""
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "invalid PNG signature"
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(raw):
        length, ctype = struct.unpack(">I4s", raw[offset : offset + 8])
        payload = raw[offset + 8 : offset + 8 + length]
        (crc_actual,) = struct.unpack(">I", raw[offset + 8 + length : offset + 12 + length])
        crc_expected = zlib.crc32(ctype + payload) & 0xFFFFFFFF
        assert crc_actual == crc_expected, f"PNG CRC mismatch on {ctype!r}"
        chunks.append((ctype, payload))
        offset += 12 + length
        if ctype == b"IEND":
            break
    assert chunks[0][0] == b"IHDR" and chunks[-1][0] == b"IEND"
    width, height, *_ = struct.unpack(">IIBBBBB", chunks[0][1])
    assert width > 0 and height > 0
    return width, height


def assert_valid_svg(raw: bytes) -> ET.Element:
    """Validate UTF-8 XML and <svg root element."""
    text_xml = raw.decode("utf-8")
    root = ET.fromstring(text_xml)
    assert root.tag.lower().endswith("svg")
    return root


def assert_valid_mp4(raw: bytes) -> None:
    """Validate ISO BMFF MP4 header (`ftyp` + `moov` box)."""
    assert len(raw) >= 24
    assert raw[4:8] == b"ftyp", f"expected MP4 ftyp box, got {raw[4:8]!r}"
    assert b"moov" in raw, "MP4 missing moov atom"


def parse_sse_events(body_text: str) -> list[dict]:
    """Parse SSE `data: ...` payloads (excluding `[DONE]`)."""
    events: list[dict] = []
    for line in body_text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            events.append(json.loads(line[len("data: ") :]))
    return events


def decode_media_response_bytes(body: dict) -> bytes:
    """Decode HealthMediaResponse.content_base64 and verify file_size_bytes."""
    raw = base64.b64decode(body["content_base64"], validate=True)
    assert len(raw) == body["file_size_bytes"]
    assert len(raw) > 0
    return raw


def make_safety_triage_input(
    *,
    severity_band: str | None = None,
    body_part: str | None = None,
    unable_to_bear_weight: bool = False,
    visible_deformity: bool = False,
    uncontrolled_bleeding: bool = False,
    chest_pain_or_breathing_difficulty: bool = False,
    new_numbness_or_weakness: bool = False,
    head_injury_with_neurological_symptoms: bool = False,
    hot_swollen_joint_with_fever: bool = False,
    collapse_confusion_or_extreme_heat_illness: bool = False,
    localized_bone_pain_worse_with_weight_bearing: bool = False,
) -> SafetyTriageInput:
    return SafetyTriageInput(
        severity_band=severity_band,
        body_part=body_part,
        unable_to_bear_weight=unable_to_bear_weight,
        visible_deformity=visible_deformity,
        uncontrolled_bleeding=uncontrolled_bleeding,
        chest_pain_or_breathing_difficulty=chest_pain_or_breathing_difficulty,
        new_numbness_or_weakness=new_numbness_or_weakness,
        head_injury_with_neurological_symptoms=head_injury_with_neurological_symptoms,
        hot_swollen_joint_with_fever=hot_swollen_joint_with_fever,
        collapse_confusion_or_extreme_heat_illness=collapse_confusion_or_extreme_heat_illness,
        localized_bone_pain_worse_with_weight_bearing=localized_bone_pain_worse_with_weight_bearing,
    )


# ---------------------------------------------------------------------------
# External-Boundary-Only Provider & HTTP Transport Doubles
# ---------------------------------------------------------------------------


@pytest.fixture()
def scripted_coach_provider(monkeypatch: pytest.MonkeyPatch):
    """Patch only the external CoachProvider factory boundary (never routes/guidance)."""
    from app import coach_providers, llm_client

    class _ScriptedCoachProvider:
        name = "scripted-e2e"

        def __init__(
            self,
            *,
            answer_text: str | Callable[[list[dict[str, str]]], str],
            json_override: dict[str, object] | None,
            stream_chunks: list[str] | None,
        ) -> None:
            self._answer_text = answer_text
            self._json_override = json_override or {}
            self._stream_chunks = stream_chunks

        @property
        def model(self) -> str:
            return "scripted-e2e-v1"

        def is_configured(self) -> bool:
            return True

        def check(self, timeout_seconds: float) -> None:
            return None

        def complete(
            self,
            messages: list[dict[str, str]],
            *,
            temperature: float,
            as_json: bool = False,
            timeout_seconds: float = 8.0,
        ) -> str:
            if as_json:
                return json.dumps(self._json_override, ensure_ascii=False)
            if callable(self._answer_text):
                return self._answer_text(messages)
            return self._answer_text

        def stream(
            self, messages: list[dict[str, str]], *, temperature: float
        ) -> Iterator[str]:
            if self._stream_chunks is not None:
                yield from self._stream_chunks
                return
            yield (
                self._answer_text(messages)
                if callable(self._answer_text)
                else self._answer_text
            )

    def _configure(
        *,
        answer_text: str | Callable[[list[dict[str, str]]], str] = "今天可以輕鬆跑 20 分鐘。",
        json_override: dict[str, object] | None = None,
        stream_chunks: list[str] | None = None,
    ) -> _ScriptedCoachProvider:
        provider = _ScriptedCoachProvider(
            answer_text=answer_text,
            json_override=json_override,
            stream_chunks=stream_chunks,
        )
        monkeypatch.setattr(llm_client, "configured_coach_provider", lambda: provider)
        monkeypatch.setattr(coach_providers, "configured_coach_provider", lambda: provider)
        return provider

    return _configure


@pytest.fixture()
def scripted_groq_transport(monkeypatch: pytest.MonkeyPatch):
    """Set GROQ_API_KEY and intercept only groq_client.GROQ_URL on httpx.post."""
    from app import groq_client

    orig_post = httpx.post

    def _configure(
        handler: Callable[[dict[str, object]], dict[str, object] | str],
    ) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "gsk_e2e_offline_stub")

        def _fake_post(url, *args, **kwargs):
            if str(url) == groq_client.GROQ_URL:
                body = kwargs.get("json") or {}
                result = handler(body)
                content = (
                    json.dumps(result, ensure_ascii=False)
                    if isinstance(result, dict)
                    else str(result)
                )
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", str(url)),
                    json={"choices": [{"message": {"content": content}}]},
                )
            return orig_post(url, *args, **kwargs)

        monkeypatch.setattr(httpx, "post", _fake_post)

    return _configure

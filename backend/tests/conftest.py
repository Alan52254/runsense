from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.main import app
from app.providers import InMemoryProfileTimezoneProvider, StaticCurrentActorProvider
from app.routes import activities as activities_module
from app.routes import training_load as training_load_routes_module

# DB-dependent tests are intentionally restricted to an explicit, isolated
# TEST_DATABASE_URL. These fixtures truncate every application table before
# and after a test, so falling back to DATABASE_URL can erase a developer's
# runtime/demo data.
_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
_RUNTIME_DATABASE_URL = os.environ.get("DATABASE_URL")


def _database_identity(url: str) -> tuple[str, int, str | None]:
    parsed = make_url(url)
    return (parsed.host or "localhost", parsed.port or 5432, parsed.database)


if (
    _TEST_DATABASE_URL
    and _RUNTIME_DATABASE_URL
    and _database_identity(_TEST_DATABASE_URL) == _database_identity(_RUNTIME_DATABASE_URL)
):
    raise RuntimeError(
        "TEST_DATABASE_URL must point to a database separate from DATABASE_URL; "
        "the test suite truncates application tables."
    )


def _db_available() -> bool:
    if not _TEST_DATABASE_URL:
        return False
    try:
        engine = create_engine(_TEST_DATABASE_URL, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_available(),
    reason=(
        "No reachable isolated Postgres test database. Set TEST_DATABASE_URL "
        "to a separate database with migrations applied -- "
        "see backend/docker-compose.yml."
    ),
)


@pytest.fixture()
def admin_engine() -> Iterator[Engine]:
    engine = create_engine(_TEST_DATABASE_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_table(request: pytest.FixtureRequest) -> Iterator[None]:
    if "requires_db" not in request.keywords and not _db_available():
        yield
        return
    if not _db_available():
        yield
        return
    engine = create_engine(_TEST_DATABASE_URL, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE chat_reads, chat_cards, chat_messages, chat_rooms, assignment_batches, "
                "coach_proposals, workout_analyses, workout_prescriptions, activity_telemetry, "
                "assigned_workouts, audit_log, auth_sessions, "
                "injury_report_details, injury_reports, daily_guidance_cache, weather_cache, training_load_daily, "
                "athlete_rest_days, completed_activities, consent_grants, team_memberships, "
                "teams, athlete_profiles, users"
            )
        )
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE chat_reads, chat_cards, chat_messages, chat_rooms, assignment_batches, "
                "coach_proposals, workout_analyses, workout_prescriptions, activity_telemetry, "
                "assigned_workouts, audit_log, auth_sessions, "
                "injury_report_details, injury_reports, daily_guidance_cache, weather_cache, training_load_daily, "
                "athlete_rest_days, completed_activities, consent_grants, team_memberships, "
                "teams, athlete_profiles, users"
            )
        )
    engine.dispose()


def _get_connection_as_runtime_role() -> Iterator:
    """Test-time substitute for a real runsense_runtime login.

    Connects with whatever role TEST_DATABASE_URL authenticates as (expected
    to be an admin/superuser in local/dev/test), then SET ROLE to
    runsense_runtime for the duration of the request so RLS is actually
    exercised as the runtime role would see it in production. Production
    instead authenticates directly as runsense_runtime with real
    credentials -- this SET ROLE dance is test-only plumbing, not part of
    the application.
    """
    engine = create_engine(_TEST_DATABASE_URL, future=True)
    with engine.connect() as conn:
        conn.execute(text("SET ROLE runsense_runtime"))
        # SET ROLE persists on the session regardless of transaction state;
        # commit here so the autobegun transaction from the execute() above
        # doesn't linger -- app.db.actor_transaction calls conn.begin()
        # itself and requires the connection to have no transaction open yet.
        conn.commit()
        try:
            yield conn
        finally:
            conn.execute(text("RESET ROLE"))
            conn.commit()
    engine.dispose()


class ClientFactory:
    """Builds a TestClient with actor/timezone providers overridden per test."""

    def __call__(
        self,
        *,
        actor_id: str | None,
        timezones: dict[str, str] | None = None,
        actor_dependency: Callable | None = None,
        clock=None,
        raise_server_exceptions: bool = True,
    ) -> TestClient:
        app.dependency_overrides[activities_module.get_current_actor_provider] = (
            actor_dependency
            if actor_dependency is not None
            else lambda: StaticCurrentActorProvider(actor_id)
        )
        app.dependency_overrides[activities_module.get_profile_timezone_provider] = (
            lambda: InMemoryProfileTimezoneProvider(timezones or {})
        )
        app.dependency_overrides[activities_module.get_connection] = (
            _get_connection_as_runtime_role
        )
        if clock is None:
            app.dependency_overrides.pop(training_load_routes_module.get_clock, None)
        else:
            app.dependency_overrides[training_load_routes_module.get_clock] = (
                lambda: clock
            )
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture()
def make_client() -> Iterator[ClientFactory]:
    factory = ClientFactory()
    yield factory
    app.dependency_overrides.clear()


@pytest.fixture()
def new_athlete_id() -> str:
    return str(uuid.uuid4())

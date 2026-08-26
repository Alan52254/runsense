"""DB-dependent RLS and schema tests. Requires TEST_DATABASE_URL /
DATABASE_URL pointing at a Postgres instance with migrations applied
(alembic upgrade head).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from conftest import requires_db


@requires_db
def test_tc_schema_dataown_001_no_team_id_column(admin_engine):
    with admin_engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'completed_activities'"
            )
        ).scalars().all()
    assert "team_id" not in columns


@requires_db
@pytest.mark.parametrize("non_finite_numeric", ["Infinity", "NaN"])
def test_completed_activity_duration_must_be_finite_in_storage(
    admin_engine, non_finite_numeric
):
    with pytest.raises(IntegrityError):
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO completed_activities "
                    "(athlete_id, client_mutation_id, request_fingerprint, "
                    " duration_minutes, rpe, performed_at, timezone_snapshot, "
                    " local_training_date, session_load) "
                    "VALUES (:athlete_id, :cmid, 'non-finite-duration', "
                    " CAST(:duration AS numeric), 1, now(), 'UTC', current_date, 1)"
                ),
                {
                    "athlete_id": str(uuid.uuid4()),
                    "cmid": str(uuid.uuid4()),
                    "duration": non_finite_numeric,
                },
            )


@requires_db
def test_tc_rls_010_rls_enabled_and_forced(admin_engine):
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'completed_activities'"
            )
        ).one()
    assert row.relrowsecurity is True
    assert row.relforcerowsecurity is True


@requires_db
def test_tc_rls_006_runtime_role_not_table_owner(admin_engine):
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT tableowner FROM pg_tables WHERE tablename = 'completed_activities'"
            )
        ).one()
    assert row.tableowner != "runsense_runtime"


@requires_db
def test_tc_rls_007_runtime_role_has_no_bypassrls(admin_engine):
    with admin_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'runsense_runtime'")
        ).one()
    assert row.rolbypassrls is False
    assert row.rolsuper is False


@requires_db
def test_tc_rls_008_set_local_does_not_leak_across_transactions(admin_engine):
    """SET LOCAL (via set_config(..., true)) is transaction-scoped: a second
    transaction on the same connection that doesn't set the actor context
    must not inherit the first transaction's value.
    """
    athlete_a = str(uuid.uuid4())
    with admin_engine.connect() as conn:
        conn.execute(text("SET ROLE runsense_runtime"))
        conn.commit()  # close the autobegun transaction before conn.begin()
        try:
            with conn.begin():
                conn.execute(
                    text("SELECT set_config('app.actor_user_id', :id, true)"),
                    {"id": athlete_a},
                )
                conn.execute(
                    text(
                        "INSERT INTO completed_activities "
                        "(athlete_id, client_mutation_id, request_fingerprint, "
                        " duration_minutes, rpe, performed_at, timezone_snapshot, "
                        " local_training_date, session_load) "
                        "VALUES (:athlete_id, :cmid, 'fp-a', 45, 6, now(), 'UTC', "
                        " current_date, 270)"
                    ),
                    {"athlete_id": athlete_a, "cmid": str(uuid.uuid4())},
                )

            # New transaction, same connection, no actor context set.
            with conn.begin():
                visible = conn.execute(
                    text("SELECT count(*) FROM completed_activities WHERE athlete_id = :id"),
                    {"id": athlete_a},
                ).scalar_one()
            assert visible == 0, "actor context leaked across transaction boundary"
        finally:
            conn.execute(text("RESET ROLE"))


@requires_db
def test_tc_rls_011_forged_target_does_not_grant_cross_athlete_access(make_client, admin_engine):
    athlete_a = str(uuid.uuid4())
    athlete_b = str(uuid.uuid4())

    client_a = make_client(actor_id=athlete_a, timezones={athlete_a: "Asia/Taipei"})
    created = client_a.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    assert created.status_code == 201

    # Attacker B tries to reach A's row via a replay of the *same*
    # client_mutation_id under B's own actor context. RLS must scope the
    # idempotency SELECT to B's own rows -- the forged/reused key must not
    # surface A's row to B.
    same_mutation_id = created.json()["client_mutation_id"]
    client_b = make_client(actor_id=athlete_b, timezones={athlete_b: "Asia/Taipei"})
    attempt = client_b.post(
        "/activities",
        json={
            "client_mutation_id": same_mutation_id,
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-08-07T09:15:00Z",
        },
    )
    # B has no existing row under (athlete_b, same_mutation_id), so this is
    # a fresh insert for B -- a *new* row is created, not A's row returned.
    assert attempt.status_code == 201
    assert attempt.json()["id"] != created.json()["id"]
    assert attempt.json()["athlete_id"] == athlete_b

    # Confirm directly against storage that B's session never saw A's row.
    with admin_engine.connect() as conn:
        conn.execute(text("SET ROLE runsense_runtime"))
        conn.commit()  # close the autobegun transaction before conn.begin()
        try:
            with conn.begin():
                conn.execute(
                    text("SELECT set_config('app.actor_user_id', :id, true)"),
                    {"id": athlete_b},
                )
                visible_ids = conn.execute(
                    text("SELECT id FROM completed_activities")
                ).scalars().all()
        finally:
            conn.execute(text("RESET ROLE"))
    assert str(created.json()["id"]) not in [str(i) for i in visible_ids]
    assert str(attempt.json()["id"]) in [str(i) for i in visible_ids]

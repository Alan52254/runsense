from __future__ import annotations

import uuid

from sqlalchemy import text

from conftest import requires_db


@requires_db
def test_training_load_tables_have_athlete_owned_keys_and_no_team_id(admin_engine):
    with admin_engine.connect() as conn:
        columns = {
            table: conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:table"
                ),
                {"table": table},
            ).scalars().all()
            for table in ("athlete_rest_days", "training_load_daily")
        }
        primary_keys = conn.execute(
            text(
                "SELECT tc.table_name, array_agg(kcu.column_name ORDER BY kcu.ordinal_position) "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
                "WHERE tc.table_schema='public' AND tc.constraint_type='PRIMARY KEY' "
                "AND tc.table_name IN ('athlete_rest_days','training_load_daily') "
                "GROUP BY tc.table_name"
            )
        ).all()
    assert all("team_id" not in value for value in columns.values())
    assert dict(primary_keys) == {
        "athlete_rest_days": "{athlete_id,date}",
        "training_load_daily": "{athlete_id,date,unit}",
    }


@requires_db
def test_training_load_tables_force_actor_rls_and_runtime_privileges(admin_engine):
    with admin_engine.connect() as conn:
        rls = conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('athlete_rest_days','training_load_daily')"
            )
        ).all()
        privileges = conn.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee='runsense_runtime' "
                "AND table_name IN ('athlete_rest_days','training_load_daily')"
            )
        ).all()
    assert {(row.relname, row.relrowsecurity, row.relforcerowsecurity) for row in rls} == {
        ("athlete_rest_days", True, True),
        ("training_load_daily", True, True),
    }
    assert set(privileges) == {
        (table, privilege)
        for table in ("athlete_rest_days", "training_load_daily")
        for privilege in ("SELECT", "INSERT", "DELETE")
    }


@requires_db
def test_rest_day_rls_isolates_actors_and_missing_context(admin_engine):
    athlete_a, athlete_b = str(uuid.uuid4()), str(uuid.uuid4())
    with admin_engine.connect() as conn:
        conn.execute(text("SET ROLE runsense_runtime"))
        conn.commit()
        try:
            with conn.begin():
                conn.execute(text("SELECT set_config('app.actor_user_id', :id, true)"), {"id": athlete_a})
                conn.execute(
                    text("INSERT INTO athlete_rest_days (athlete_id,date) VALUES (:id,'2026-08-01')"),
                    {"id": athlete_a},
                )
            with conn.begin():
                conn.execute(text("SELECT set_config('app.actor_user_id', :id, true)"), {"id": athlete_b})
                assert conn.execute(text("SELECT count(*) FROM athlete_rest_days")).scalar_one() == 0
            with conn.begin():
                assert conn.execute(text("SELECT count(*) FROM athlete_rest_days")).scalar_one() == 0
        finally:
            conn.execute(text("RESET ROLE"))
            conn.commit()


@requires_db
def test_training_load_declared_constraints_exist(admin_engine):
    with admin_engine.connect() as conn:
        names = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid='training_load_daily'::regclass"
                )
            ).scalars()
        )
        index_names = set(
            conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename='training_load_daily'")
            ).scalars()
        )
    assert {
        "ck_training_load_daily_session_load",
        "ck_training_load_daily_acute_load",
        "ck_training_load_daily_chronic_load",
        "ck_training_load_daily_ratio",
        "ck_training_load_daily_quality",
        "ck_training_load_daily_observations",
        "ck_training_load_daily_versions",
        "ck_training_load_daily_hash",
    } <= names
    assert "ix_training_load_daily_athlete_date" in index_names

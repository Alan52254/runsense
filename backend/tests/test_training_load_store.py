from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

from sqlalchemy import text

from app.db import actor_transaction
from app.training_load_store import recompute_training_load
from conftest import requires_db


@requires_db
def test_recompute_changes_only_d_through_d_plus_27(admin_engine):
    athlete_id = str(uuid.uuid4())
    changed = date(2026, 8, 1)
    before = changed - timedelta(days=1)
    after = changed + timedelta(days=28)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO completed_activities "
                "(athlete_id,client_mutation_id,request_fingerprint,duration_minutes,rpe,"
                "performed_at,timezone_snapshot,local_training_date,session_load) "
                "VALUES (:athlete_id,:mutation_id,'store-test',10,5,"
                "'2026-08-01T10:00:00Z','UTC',:changed,50)"
            ),
            {
                "athlete_id": athlete_id,
                "mutation_id": str(uuid.uuid4()),
                "changed": changed,
            },
        )
        for point_date in (before, after):
            conn.execute(
                text(
                    "INSERT INTO training_load_daily "
                    "(athlete_id,date,unit,session_load,source_metric,acute_load,chronic_load,"
                    "load_ratio,data_quality,observation_days,algorithm_version,schema_version,"
                    "computed_at,input_snapshot_hash) VALUES "
                    "(:athlete_id,:date,'AU',0,'SESSION_RPE',0,0,NULL,'INSUFFICIENT',0,"
                    "'sentinel',1,'2000-01-01T00:00:00Z',repeat('a',64))"
                ),
                {"athlete_id": athlete_id, "date": point_date},
            )

    with admin_engine.connect() as conn:
        with actor_transaction(conn, athlete_id) as tx:
            recompute_training_load(tx, uuid.UUID(athlete_id), changed)

    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT date,algorithm_version,computed_at FROM training_load_daily "
                "WHERE athlete_id=:athlete_id ORDER BY date"
            ),
            {"athlete_id": athlete_id},
        ).all()
    assert rows[0].date == before and rows[0].algorithm_version == "sentinel"
    assert rows[-1].date == after and rows[-1].algorithm_version == "sentinel"
    affected = [row for row in rows if changed <= row.date <= changed + timedelta(days=27)]
    assert len(affected) == 28
    assert {row.algorithm_version for row in affected} == {"tl-v1"}


@requires_db
def test_new_activity_clears_rest_and_materializes_before_response(
    make_client, admin_engine, new_athlete_id
):
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO athlete_rest_days (athlete_id,date) "
                "VALUES (:athlete_id,'2026-08-01')"
            ),
            {"athlete_id": new_athlete_id},
        )
    client = make_client(
        actor_id=new_athlete_id, timezones={new_athlete_id: "UTC"}
    )
    response = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 10,
            "rpe": 5,
            "performed_at": "2026-08-01T10:00:00Z",
        },
    )
    assert response.status_code == 201, response.text
    with admin_engine.connect() as conn:
        rest_count = conn.execute(
            text("SELECT count(*) FROM athlete_rest_days WHERE athlete_id=:id"),
            {"id": new_athlete_id},
        ).scalar_one()
        point = conn.execute(
            text(
                "SELECT session_load,algorithm_version FROM training_load_daily "
                "WHERE athlete_id=:id AND date='2026-08-01' AND unit='AU'"
            ),
            {"id": new_athlete_id},
        ).one()
    assert rest_count == 0
    assert point.session_load == 50
    assert point.algorithm_version == "tl-v1"


@requires_db
def test_idempotent_activity_replay_does_not_recompute(
    make_client, admin_engine, new_athlete_id
):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "UTC"})
    payload = {
        "client_mutation_id": str(uuid.uuid4()),
        "duration_minutes": 10,
        "rpe": 5,
        "performed_at": "2026-08-01T10:00:00Z",
    }
    assert client.post("/activities", json=payload).status_code == 201
    with admin_engine.connect() as conn:
        before = conn.execute(
            text(
                "SELECT max(computed_at) FROM training_load_daily WHERE athlete_id=:id"
            ),
            {"id": new_athlete_id},
        ).scalar_one()
    assert client.post("/activities", json=payload).status_code == 200
    with admin_engine.connect() as conn:
        after = conn.execute(
            text(
                "SELECT max(computed_at) FROM training_load_daily WHERE athlete_id=:id"
            ),
            {"id": new_athlete_id},
        ).scalar_one()
    assert after == before


@requires_db
def test_activity_insert_rolls_back_when_materialization_fails(
    make_client, admin_engine, new_athlete_id
):
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO completed_activities "
                "(athlete_id,client_mutation_id,request_fingerprint,duration_minutes,rpe,"
                "performed_at,timezone_snapshot,local_training_date,session_load) "
                "VALUES (:athlete_id,:mutation_id,'invalid-canonical-load',10,5,"
                "'2026-08-01T09:00:00Z','UTC','2026-08-01','Infinity'::numeric)"
            ),
            {
                "athlete_id": new_athlete_id,
                "mutation_id": str(uuid.uuid4()),
            },
        )

    client = make_client(
        actor_id=new_athlete_id,
        timezones={new_athlete_id: "UTC"},
        raise_server_exceptions=False,
    )
    new_mutation_id = str(uuid.uuid4())
    response = client.post(
        "/activities",
        json={
            "client_mutation_id": new_mutation_id,
            "duration_minutes": 10,
            "rpe": 5,
            "performed_at": "2026-08-01T10:00:00Z",
        },
    )
    assert response.status_code == 500
    with admin_engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT count(*) FROM completed_activities "
                "WHERE athlete_id=:id AND client_mutation_id=:mutation_id"
            ),
            {"id": new_athlete_id, "mutation_id": new_mutation_id},
        ).scalar_one() == 0


@requires_db
def test_adjacent_date_mutations_leave_overlapping_projection_current(
    make_client, new_athlete_id
):
    client = make_client(actor_id=new_athlete_id, timezones={new_athlete_id: "UTC"})
    barrier = Barrier(2)

    def create(performed_at: str, duration: int):
        barrier.wait()
        return client.post(
            "/activities",
            json={
                "client_mutation_id": str(uuid.uuid4()),
                "duration_minutes": duration,
                "rpe": 5,
                "performed_at": performed_at,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda args: create(*args),
                [
                    ("2026-08-01T10:00:00Z", 10),
                    ("2026-08-02T10:00:00Z", 12),
                ],
            )
        )
    assert [response.status_code for response in responses] == [201, 201]

    body = client.get("/training-load/trend?end_date=2026-08-28").json()
    points = {point["date"]: point for point in body["series"][0]["points"]}
    assert points["2026-08-01"]["session_load"] == 50
    assert points["2026-08-02"]["session_load"] == 60
    assert points["2026-08-02"]["acute_load"] == 110

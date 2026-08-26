from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import Depends, Request
from sqlalchemy import text

from app.clock import FixedClock
from app.providers import DemoCurrentActorProvider
from app.routes import activities as activities_module
from conftest import requires_db


def _assert_no_alert_semantics(value):
    forbidden = ("alert", "risk", "threshold", "red", "yellow", "green")
    if isinstance(value, dict):
        for key, child in value.items():
            assert not any(word in key.lower() for word in forbidden)
            _assert_no_alert_semantics(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_alert_semantics(child)
    elif isinstance(value, str):
        assert not any(word in value.lower() for word in forbidden)


@requires_db
def test_explicit_empty_trend_returns_28_ascending_persisted_au_points(
    make_client, admin_engine, new_athlete_id
):
    client = make_client(actor_id=new_athlete_id)
    response = client.get("/training-load/trend?end_date=2026-08-28")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start_date"] == "2026-08-01"
    assert body["end_date"] == "2026-08-28"
    assert [series["unit"] for series in body["series"]] == ["AU"]
    points = body["series"][0]["points"]
    assert len(points) == 28
    assert [point["date"] for point in points] == [
        str(date(2026, 8, 1) + timedelta(days=i)) for i in range(28)
    ]
    assert all(point["data_quality"] == "INSUFFICIENT" for point in points)
    assert all(point["load_ratio"] is None for point in points)
    with admin_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM training_load_daily WHERE athlete_id=:id"),
            {"id": new_athlete_id},
        ).scalar_one() == 28
    _assert_no_alert_semantics(body)


@requires_db
def test_omitted_end_date_uses_profile_timezone_at_utc_boundary(
    make_client, new_athlete_id
):
    client = make_client(
        actor_id=new_athlete_id,
        timezones={new_athlete_id: "Asia/Taipei"},
        clock=FixedClock(datetime(2026, 8, 1, 16, 30, tzinfo=timezone.utc)),
    )
    response = client.get("/training-load/trend")
    assert response.status_code == 200
    assert response.json()["end_date"] == "2026-08-02"


@requires_db
def test_all_rest_and_silent_dates_have_distinct_observation_semantics(
    make_client, admin_engine, new_athlete_id
):
    end = date(2026, 8, 28)
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO athlete_rest_days (athlete_id,date) VALUES (:id,:date)"),
            [
                {"id": new_athlete_id, "date": end - timedelta(days=i)}
                for i in range(28)
            ],
        )
    body = make_client(actor_id=new_athlete_id).get(
        "/training-load/trend?end_date=2026-08-28"
    ).json()
    final = body["series"][0]["points"][-1]
    assert final["observation_days"] == 28
    assert final["chronic_load"] == 0
    assert final["data_quality"] == "INSUFFICIENT"
    assert final["load_ratio"] is None

    silent = make_client(actor_id=str(uuid.uuid4())).get(
        "/training-load/trend?end_date=2026-08-28"
    ).json()["series"][0]["points"][-1]
    assert silent["observation_days"] == 0


@requires_db
def test_mixed_units_return_separate_low_quality_series(
    make_client, admin_engine, new_athlete_id
):
    end = date(2026, 8, 28)
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO athlete_rest_days (athlete_id,date) VALUES (:id,:date)"),
            [
                {"id": new_athlete_id, "date": end - timedelta(days=i)}
                for i in range(1, 28)
            ],
        )
        base = (
            "INSERT INTO completed_activities "
            "(athlete_id,client_mutation_id,request_fingerprint,provider,duration_minutes,rpe,"
            "performed_at,timezone_snapshot,local_training_date,session_load,unit,source_metric) "
            "VALUES (:id,:mutation,:fp,:provider,10,5,:performed,'UTC',:date,300,:unit,:metric)"
        )
        conn.execute(
            text(base),
            [
                {
                    "id": new_athlete_id,
                    "mutation": str(uuid.uuid4()),
                    "fp": "mixed-au",
                    "provider": "manual",
                    "performed": datetime(2026, 8, 28, tzinfo=timezone.utc),
                    "date": end,
                    "unit": "AU",
                    "metric": "SESSION_RPE",
                },
                {
                    "id": new_athlete_id,
                    "mutation": str(uuid.uuid4()),
                    "fp": "mixed-epoc",
                    "provider": "garmin",
                    "performed": datetime(2026, 8, 28, 1, tzinfo=timezone.utc),
                    "date": end,
                    "unit": "garmin_epoc",
                    "metric": "GARMIN_EPOC",
                },
            ],
        )
    body = make_client(actor_id=new_athlete_id).get(
        "/training-load/trend?end_date=2026-08-28"
    ).json()
    assert [series["unit"] for series in body["series"]] == ["AU", "garmin_epoc"]
    assert [series["points"][-1]["session_load"] for series in body["series"]] == [300, 300]
    assert [series["points"][-1]["data_quality"] for series in body["series"]] == ["LOW", "LOW"]
    assert "combined" not in body


@requires_db
def test_trend_auth_identity_date_and_timezone_fail_closed(make_client):
    assert make_client(actor_id=None).get(
        "/training-load/trend?end_date=2026-08-28"
    ).status_code == 403
    assert make_client(actor_id="bad").get(
        "/training-load/trend?end_date=2026-08-28"
    ).status_code == 403
    athlete_id = str(uuid.uuid4())
    assert make_client(actor_id=athlete_id).get(
        "/training-load/trend?end_date=not-a-date"
    ).status_code == 422
    assert make_client(actor_id=athlete_id, timezones={}).get(
        "/training-load/trend"
    ).status_code == 422
    forged = make_client(actor_id=athlete_id).get(
        f"/training-load/trend?end_date=2026-08-28&athlete_id={uuid.uuid4()}"
    )
    assert forged.status_code == 200
    assert len(forged.json()["series"]) == 1


@requires_db
def test_expired_demo_token_is_rejected_by_trend_interface(make_client):
    secret = "test-only-trend-secret-at-least-32-bytes"
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "exp": datetime(2020, 1, 1, tzinfo=timezone.utc),
        },
        secret,
        algorithm="HS256",
    )

    def demo_actor_dependency(
        request: Request,
        conn=Depends(activities_module.get_connection),
    ):
        return DemoCurrentActorProvider(request, conn, secret=secret)

    client = make_client(actor_id=None, actor_dependency=demo_actor_dependency)
    response = client.get(
        "/training-load/trend?end_date=2026-08-28",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}

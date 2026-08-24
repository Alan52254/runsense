from __future__ import annotations

import uuid

from sqlalchemy import text

from conftest import requires_db


def _seed_athlete(admin_engine) -> uuid.UUID:
    athlete_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": athlete_id, "email": f"injury-{athlete_id}@example.test"},
        )
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:id, 'Asia/Taipei')"),
            {"id": athlete_id},
        )
    return athlete_id


@requires_db
def test_athlete_creates_and_lists_split_injury_report(make_client, admin_engine):
    athlete_id = _seed_athlete(admin_engine)
    client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    mutation_id = uuid.uuid4()

    created = client.post(
        "/injury-reports",
        json={
            "client_mutation_id": str(mutation_id),
            "has_issue": True,
            "severity_band": "MILD",
            "body_part": "右小腿",
            "free_text": "下樓梯時有緊繃感",
            "reported_at": "2026-08-24T16:30:00Z",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["local_training_date"] == "2026-08-25"
    assert created.json()["free_text"] == "下樓梯時有緊繃感"

    history = client.get("/injury-reports")
    assert history.status_code == 200, history.text
    assert history.json()["items"] == [created.json()]

    with admin_engine.connect() as conn:
        summary_columns = {
            row.column_name
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='injury_reports'"
                )
            )
        }
        assert "free_text" not in summary_columns
        assert conn.execute(text("SELECT count(*) FROM injury_report_details")).scalar_one() == 1


@requires_db
def test_injury_report_retry_is_idempotent(make_client, admin_engine):
    athlete_id = _seed_athlete(admin_engine)
    client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "UTC"})
    payload = {
        "client_mutation_id": str(uuid.uuid4()),
        "has_issue": False,
        "severity_band": "NONE",
        "body_part": None,
        "free_text": None,
        "reported_at": "2026-08-24T08:00:00Z",
    }

    first = client.post("/injury-reports", json=payload)
    second = client.post("/injury-reports", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()


@requires_db
def test_injury_report_rejects_inconsistent_no_issue_payload(make_client, admin_engine):
    athlete_id = _seed_athlete(admin_engine)
    client = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "UTC"})
    response = client.post(
        "/injury-reports",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "has_issue": False,
            "severity_band": "SEVERE",
            "body_part": "左膝",
            "free_text": None,
            "reported_at": "2026-08-24T08:00:00Z",
        },
    )
    assert response.status_code == 422


@requires_db
def test_coach_injury_summary_and_detail_are_independently_gated(make_client, admin_engine):
    athlete_id = _seed_athlete(admin_engine)
    coach_id, team_id = uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": coach_id, "email": f"coach-injury-{coach_id}@example.test"},
        )
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:id, 'UTC')"),
            {"id": coach_id},
        )
        conn.execute(text("INSERT INTO teams (id, name) VALUES (:id, 'Injury Team')"), {"id": team_id})
        conn.execute(
            text(
                "INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) VALUES "
                "(:team, :coach, 'coach', 'ACTIVE', now()), "
                "(:team, :athlete, 'athlete', 'ACTIVE', now())"
            ),
            {"team": team_id, "coach": coach_id, "athlete": athlete_id},
        )
        for scope in ("injury_status", "injury_detail"):
            conn.execute(
                text(
                    "INSERT INTO consent_grants (team_id, athlete_id, scope, granted) "
                    "VALUES (:team, :athlete, :scope, false)"
                ),
                {"team": team_id, "athlete": athlete_id, "scope": scope},
            )

    athlete = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    created = athlete.post(
        "/injury-reports",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "has_issue": True,
            "severity_band": "MODERATE",
            "body_part": "左膝",
            "free_text": "落地時刺痛",
            "reported_at": "2026-08-24T08:00:00Z",
        },
    )
    assert created.status_code == 201, created.text

    athlete.patch(
        "/me/consent-grants/injury_status",
        json={"team_id": str(team_id), "granted": True},
    )
    coach = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    status_only = coach.get(f"/teams/{team_id}/roster").json()["items"][0]
    assert status_only["injury_has_issue"] is True
    assert status_only["injury_severity_band"] == "MODERATE"
    assert status_only["injury_free_text"] is None

    athlete = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    athlete.patch(
        "/me/consent-grants/injury_status",
        json={"team_id": str(team_id), "granted": False},
    )
    athlete.patch(
        "/me/consent-grants/injury_detail",
        json={"team_id": str(team_id), "granted": True},
    )
    coach = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    detail_only = coach.get(f"/teams/{team_id}/roster").json()["items"][0]
    assert detail_only["injury_has_issue"] is None
    assert detail_only["injury_severity_band"] is None
    assert detail_only["injury_free_text"] == "落地時刺痛"


@requires_db
def test_latest_summary_never_pairs_with_detail_from_an_older_report(make_client, admin_engine):
    athlete_id = _seed_athlete(admin_engine)
    coach_id, team_id = uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": coach_id, "email": f"coach-latest-{coach_id}@example.test"},
        )
        conn.execute(
            text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:id, 'UTC')"),
            {"id": coach_id},
        )
        conn.execute(text("INSERT INTO teams (id, name) VALUES (:id, 'Latest Injury Team')"), {"id": team_id})
        conn.execute(
            text(
                "INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) VALUES "
                "(:team, :coach, 'coach', 'ACTIVE', now()), "
                "(:team, :athlete, 'athlete', 'ACTIVE', now())"
            ),
            {"team": team_id, "coach": coach_id, "athlete": athlete_id},
        )
        for scope in ("injury_status", "injury_detail"):
            conn.execute(
                text(
                    "INSERT INTO consent_grants (team_id, athlete_id, scope, granted) "
                    "VALUES (:team, :athlete, :scope, true)"
                ),
                {"team": team_id, "athlete": athlete_id, "scope": scope},
            )

    athlete = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    older = athlete.post(
        "/injury-reports",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "has_issue": True,
            "severity_band": "MILD",
            "body_part": "左膝",
            "free_text": "舊的自述不應沿用",
            "reported_at": "2026-08-23T08:00:00Z",
        },
    )
    assert older.status_code == 201
    newer = athlete.post(
        "/injury-reports",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "has_issue": True,
            "severity_band": "MODERATE",
            "body_part": "右小腿",
            "free_text": None,
            "reported_at": "2026-08-24T08:00:00Z",
        },
    )
    assert newer.status_code == 201

    coach = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    row = coach.get(f"/teams/{team_id}/roster").json()["items"][0]
    assert row["injury_severity_band"] == "MODERATE"
    assert row["injury_free_text"] is None

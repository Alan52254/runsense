"""Tier 1 E2E tests: 45 isolated happy-path functional tests (5 per feature F1-F9)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import uuid

import jwt
import pytest
from sqlalchemy import text

from app.athlete_pace import pace_range
from app.fit_telemetry import FitParseError, parse_fit, peak_rolling_hr
from app.garmin_ingest import compute_hr_trimp_rpe
from app.injury_guidance import EvidencePassage, compose_injury_guidance
from app.plan_ranking import MLPlanRanker, configured_plan_ranker
from app.plan_scenario import AthleteFacts, ScenarioOverride, evaluate_scenario, resolve_scenario
from app.react_coach import AgentSecurityEnvelope, run_unified_react_coach
from app.routes.guidance import CoachChatResponse
from app.safety_triage import (
    RULE_VERSION as SAFETY_RULE_VERSION,
    SafetyTriageInput,
    TriageUrgency,
    assess_safety_triage,
    assess_safety_triage_text,
)
from app.schemas import ScenarioOverrideRequest
from app.training_plan_candidates import (
    TrainingPlanContext,
    WorkoutType,
    generate_training_plan_candidates,
)
from app.workout_analysis import resolve_hr_profile

from tests.e2e.conftest import (
    E2E_DEMO_SECRET,
    _get_connection_as_runtime_role,
    assert_valid_mp4,
    assert_valid_png,
    assert_valid_svg,
    build_synthetic_fit_bytes,
    build_synthetic_garmin_gdpr_bundle,
    decode_media_response_bytes,
    make_safety_triage_input,
    parse_sse_events,
    requires_db,
    seed_team_and_members,
    seed_user,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_tier1]

_FIXED_UTC = datetime(2026, 11, 23, 8, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 11, 23)


# ===========================================================================
# F1: Identity, Demo Auth, MFA Step-Up & Settings/Privacy
# ===========================================================================


@requires_db
@pytest.mark.e2e_db
def test_t1_f1_01_demo_login_issues_jwt_and_records_audit_log(
    admin_engine, make_e2e_demo_client
) -> None:
    user_id = seed_user(admin_engine, email="f1-01@runsense.e2e", password="DemoPass!2026")
    client = make_e2e_demo_client(clock_utc=_FIXED_UTC)

    login = client.post(
        "/auth/demo-login",
        json={"email": "f1-01@runsense.e2e", "password": "DemoPass!2026"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    claims = jwt.decode(token, E2E_DEMO_SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(user_id)
    assert "sid" in claims and "exp" in claims

    audit = client.get("/me/settings/audit-log", headers={"Authorization": f"Bearer {token}"})
    assert audit.status_code == 200, audit.text
    events = [item["event"] for item in audit.json()["items"]]
    assert "AUTH_LOGIN" in events


@requires_db
@pytest.mark.e2e_db
def test_t1_f1_02_sessions_list_marks_current_and_delete_revokes(
    admin_engine, make_e2e_demo_client
) -> None:
    seed_user(admin_engine, email="f1-02@runsense.e2e", password="DemoPass!2026")
    client = make_e2e_demo_client()

    token = client.post(
        "/auth/demo-login",
        json={"email": "f1-02@runsense.e2e", "password": "DemoPass!2026"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sessions = client.get("/me/settings/sessions", headers=headers)
    assert sessions.status_code == 200, sessions.text
    items = sessions.json()["items"]
    assert len(items) == 1
    assert items[0]["is_current"] is True
    assert "ip_masked" in items[0]

    revoked = client.delete(f"/me/settings/sessions/{items[0]['id']}", headers=headers)
    assert revoked.status_code == 204

    after = client.get("/me/settings/sessions", headers=headers)
    assert after.status_code == 403
    assert after.json() == {"error": "NOT_AUTHORIZED"}


@requires_db
@pytest.mark.e2e_db
def test_t1_f1_03_mfa_verify_unlocks_coach_routes(
    admin_engine, make_e2e_demo_client
) -> None:
    coach_id = seed_user(admin_engine, email="f1-03-coach@runsense.e2e", password="DemoPass!2026")
    athlete_id = seed_user(admin_engine, email="f1-03-ath@runsense.e2e")
    team_id = seed_team_and_members(admin_engine, coach_id=coach_id, athlete_id=athlete_id)
    client = make_e2e_demo_client()

    token = client.post(
        "/auth/demo-login",
        json={"email": "f1-03-coach@runsense.e2e", "password": "DemoPass!2026"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    mfa = client.post("/me/settings/mfa/verify", json={"code": "424242"}, headers=headers)
    assert mfa.status_code == 200, mfa.text
    assert mfa.json() == {"mfa_satisfied": True}

    teams = client.get("/teams/mine", headers=headers)
    assert teams.status_code == 200, teams.text
    assert [t["team_id"] for t in teams.json()["items"]] == [str(team_id)]


@requires_db
@pytest.mark.e2e_db
def test_t1_f1_04_privacy_export_includes_activities_load_and_logs_audit(
    admin_engine, make_e2e_demo_client
) -> None:
    seed_user(admin_engine, email="f1-04@runsense.e2e", password="DemoPass!2026", timezone_name="Asia/Taipei")
    client = make_e2e_demo_client(clock_utc=_FIXED_UTC)
    token = client.post(
        "/auth/demo-login",
        json={"email": "f1-04@runsense.e2e", "password": "DemoPass!2026"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    act = client.post(
        "/activities",
        headers=headers,
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 40,
            "rpe": 5,
            "performed_at": "2026-11-23T06:00:00Z",
            "distance_km": 7.0,
        },
    )
    assert act.status_code == 201, act.text

    export = client.get("/me/settings/privacy/export", headers=headers)
    assert export.status_code == 200, export.text
    body = export.json()
    assert body["profile"]["timezone"] == "Asia/Taipei"
    assert len(body["completed_activities"]) == 1
    assert len(body["training_load_daily"]) >= 1

    audit = client.get("/me/settings/audit-log", headers=headers).json()
    assert any(item["event"] == "DATA_EXPORT" for item in audit["items"])


@requires_db
@pytest.mark.e2e_db
def test_t1_f1_05_deletion_request_and_garmin_integration_flag(
    admin_engine, make_e2e_demo_client, monkeypatch
) -> None:
    seed_user(admin_engine, email="f1-05@runsense.e2e", password="DemoPass!2026")
    client = make_e2e_demo_client()
    token = client.post(
        "/auth/demo-login",
        json={"email": "f1-05@runsense.e2e", "password": "DemoPass!2026"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    deletion = client.post("/me/settings/privacy/deletion-request", headers=headers)
    assert deletion.status_code == 200, deletion.text
    assert deletion.json()["deletion_requested_at"] is not None

    monkeypatch.setenv("GARMIN_ACTIVITY_SYNC_ENABLED", "false")
    off = client.get("/me/settings/integrations/garmin", headers=headers)
    assert off.status_code == 200 and off.json()["enabled"] is False

    monkeypatch.setenv("GARMIN_ACTIVITY_SYNC_ENABLED", "true")
    on = client.get("/me/settings/integrations/garmin", headers=headers)
    assert on.status_code == 200 and on.json()["enabled"] is True


# ===========================================================================
# F2: Activity Logging, Soft-Delete & ACWR Training Load
# ===========================================================================


@requires_db
@pytest.mark.e2e_db
def test_t1_f2_01_post_activity_derives_local_date_load_and_clears_rest_day(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine, timezone_name="Asia/Taipei")
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )

    rest = client.put("/rest-days/2026-11-23", json={"confirmed": True})
    assert rest.status_code == 200 and rest.json()["confirmed"] is True

    # 2026-11-22T18:00:00Z == 2026-11-23T02:00:00+08:00 in Asia/Taipei
    created = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-11-22T18:00:00Z",
            "distance_km": 8.0,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["local_training_date"] == "2026-11-23"
    assert body["session_load"] == 270.0
    assert body["timezone_snapshot"] == "Asia/Taipei"

    with admin_engine.connect() as conn:
        rest_row = conn.execute(
            text("SELECT 1 FROM athlete_rest_days WHERE athlete_id=:a AND date='2026-11-23'"),
            {"a": athlete_id},
        ).first()
    assert rest_row is None


@requires_db
@pytest.mark.e2e_db
def test_t1_f2_02_idempotent_activity_replay_returns_200_without_duplicate_load(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    payload = {
        "client_mutation_id": str(uuid.uuid4()),
        "duration_minutes": 30,
        "rpe": 5,
        "performed_at": "2026-11-23T06:00:00Z",
    }
    first = client.post("/activities", json=payload)
    second = client.post("/activities", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    trend = client.get("/training-load/trend?end_date=2026-11-23").json()
    au_points = [s["points"] for s in trend["series"] if s["unit"] == "AU"][0]
    today_point = [p for p in au_points if p["date"] == "2026-11-23"][0]
    assert today_point["session_load"] == 150.0


@requires_db
@pytest.mark.e2e_db
def test_t1_f2_03_activities_cursor_pagination_stable_descending(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
    )
    created_ids: list[str] = []
    for hour in (6, 8, 10):
        r = client.post(
            "/activities",
            json={
                "client_mutation_id": str(uuid.uuid4()),
                "duration_minutes": 30,
                "rpe": 4,
                "performed_at": f"2026-11-20T{hour:02d}:00:00Z",
            },
        )
        assert r.status_code == 201
        created_ids.append(r.json()["id"])

    page1 = client.get("/activities?limit=2").json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None
    page2 = client.get(f"/activities?limit=2&cursor={page1['next_cursor']}").json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None
    returned = [i["id"] for i in page1["items"]] + [i["id"] for i in page2["items"]]
    assert returned == list(reversed(created_ids))


@requires_db
@pytest.mark.e2e_db
def test_t1_f2_04_rest_day_toggle_updates_and_recomputes_acwr(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    on = client.put("/rest-days/2026-11-23", json={"confirmed": True})
    assert on.status_code == 200 and on.json() == {"date": "2026-11-23", "confirmed": True}

    trend = client.get("/training-load/trend?end_date=2026-11-23")
    assert trend.status_code == 200
    assert trend.json()["end_date"] == "2026-11-23"

    off = client.put("/rest-days/2026-11-23", json={"confirmed": False})
    assert off.status_code == 200 and off.json() == {"date": "2026-11-23", "confirmed": False}


@requires_db
@pytest.mark.e2e_db
def test_t1_f2_05_soft_delete_hides_activity_recomputes_load_and_unblocks_rest_day(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    act = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 50,
            "rpe": 7,
            "performed_at": "2026-11-23T06:00:00Z",
        },
    ).json()

    deleted = client.delete(f"/activities/{act['id']}")
    assert deleted.status_code == 204
    assert client.get("/activities").json()["items"] == []

    trend = client.get("/training-load/trend?end_date=2026-11-23").json()
    au_points = [s["points"] for s in trend["series"] if s["unit"] == "AU"][0]
    today_point = [p for p in au_points if p["date"] == "2026-11-23"][0]
    assert today_point["session_load"] == 0.0

    rest = client.put("/rest-days/2026-11-23", json={"confirmed": True})
    assert rest.status_code == 200 and rest.json()["confirmed"] is True


# ===========================================================================
# F3: Garmin FIT Telemetry, Wellness & Workout Analysis
# ===========================================================================


@requires_db
@pytest.mark.e2e_db
def test_t1_f3_01_telemetry_returns_laps_detection_and_linked_runs(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})

    main_act = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 40,
            "rpe": 6,
            "performed_at": "2026-11-23T06:30:00Z",
            "distance_km": 8.0,
        },
    ).json()
    warmup_act = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 10,
            "rpe": 3,
            "performed_at": "2026-11-23T06:00:00Z",
            "distance_km": 1.8,
        },
    ).json()

    with admin_engine.begin() as conn:
        for act_id, dur_s in ((main_act["id"], 2400), (warmup_act["id"], 600)):
            samples = {
                "t": list(range(0, dur_s, 10)),
                "d": [i * 33.3 for i in range(dur_s // 10)],
                "v": [3.33] * (dur_s // 10),
                "hr": [148] * (dur_s // 10),
                "cad": [174] * (dur_s // 10),
            }
            conn.execute(
                text(
                    "INSERT INTO activity_telemetry "
                    "(activity_id, athlete_id, source, sport, device, hr_profile, laps, timer_events, "
                    "workout_steps, samples, hr_peak_30s, auto_detection, auto_summary) "
                    "VALUES (:id, :a, 'garmin_fit', 'running', 'fr165', '{}'::jsonb, "
                    "CAST(:laps AS jsonb), '[]'::jsonb, '[]'::jsonb, CAST(:samples AS jsonb), "
                    "162, '{}'::jsonb, '{}'::jsonb)"
                ),
                {
                    "id": uuid.UUID(act_id),
                    "a": athlete_id,
                    "laps": json.dumps([{"start_offset_s": 0, "elapsed_s": dur_s, "distance_m": dur_s * 3.33}]),
                    "samples": json.dumps(samples),
                },
            )

    res = client.get(f"/activities/{main_act['id']}/telemetry")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["laps"]) == 1
    assert "detection" in body
    assert body["linked"]["warmup"]["activity_id"] == warmup_act["id"]


@requires_db
@pytest.mark.e2e_db
def test_t1_f3_02_workout_detection_returns_segments_hr_profile_and_easy_pace(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    client.patch("/profile", json={"max_hr_bpm": 195, "resting_hr_bpm": 50})

    act = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 30,
            "rpe": 5,
            "performed_at": "2026-11-23T06:00:00Z",
            "distance_km": 5.0,
        },
    ).json()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO activity_telemetry "
                "(activity_id, athlete_id, source, sport, device, hr_profile, laps, timer_events, "
                "workout_steps, samples, hr_peak_30s, auto_detection, auto_summary) "
                "VALUES (:id, :a, 'garmin_fit', 'running', 'fr165', "
                "'{\"max_hr\": 188, \"resting_hr\": 54}'::jsonb, "
                "'[{\"start_offset_s\": 0, \"elapsed_s\": 1800, \"distance_m\": 5000}]'::jsonb, "
                "'[]'::jsonb, '[]'::jsonb, "
                "'{\"t\": [0, 900, 1800], \"d\": [0, 2500, 5000], \"v\": [2.78, 2.78, 2.78], "
                "\"hr\": [140, 145, 148], \"cad\": [172, 174, 174]}'::jsonb, "
                "160, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"id": uuid.UUID(act["id"]), "a": athlete_id},
        )

    res = client.get(f"/activities/{act['id']}/workout-analysis/detection")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["hr_profile"]["max_hr"] == 195
    assert body["hr_profile"]["max_hr_source"] == "manual"
    assert "segments" in body["detection"]
    assert "segments_preview" in body


@requires_db
@pytest.mark.e2e_db
def test_t1_f3_03_workout_analysis_preview_and_persist_with_fallback_narrative(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    act = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 30,
            "rpe": 5,
            "performed_at": "2026-11-23T06:00:00Z",
            "distance_km": 5.0,
        },
    ).json()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO activity_telemetry "
                "(activity_id, athlete_id, source, sport, device, hr_profile, laps, timer_events, "
                "workout_steps, samples, hr_peak_30s, auto_detection, auto_summary) "
                "VALUES (:id, :a, 'garmin_fit', 'running', 'fr165', '{}'::jsonb, "
                "'[{\"start_offset_s\": 0, \"elapsed_s\": 1800, \"distance_m\": 5000}]'::jsonb, "
                "'[]'::jsonb, '[]'::jsonb, "
                "CAST(:samples AS jsonb), 160, '{}'::jsonb, '{}'::jsonb)"
            ),
            {
                "id": uuid.UUID(act["id"]),
                "a": athlete_id,
                "samples": json.dumps(
                    {
                        "t": list(range(0, 1801, 10)),
                        "d": [round(t * 2.78, 1) for t in range(0, 1801, 10)],
                        "v": [2.78] * 181,
                        "hr": [146] * 181,
                        "cad": [174] * 181,
                    }
                ),
            },
        )

    segments = [{"role": "steady", "start_s": 0, "end_s": 1800}]
    preview = client.post(f"/activities/{act['id']}/workout-analysis/preview", json={"segments": segments})
    assert preview.status_code == 200, preview.text

    saved = client.post(
        f"/activities/{act['id']}/workout-analysis",
        json={"segments": segments, "session_type": "easy"},
    )
    assert saved.status_code == 200, saved.text
    fetched = client.get(f"/activities/{act['id']}/workout-analysis")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["session_type"] == "easy"


@requires_db
@pytest.mark.e2e_db
def test_t1_f3_04_prescription_parse_put_get_delete_lifecycle(
    admin_engine, make_e2e_db_client, scripted_groq_transport
) -> None:
    def _groq_parse(_body: dict[str, object]) -> dict[str, object]:
        return {
            "is_workout": True,
            "blocks": [
                {
                    "reps": 4,
                    "distance_m": 1000,
                    "duration_s": None,
                    "targets": [240],
                    "target_unit": "s_per_km",
                    "rest_s": 90,
                    "target_mode": "exact",
                }
            ],
            "warmup": None,
            "cooldown": None,
        }

    scripted_groq_transport(_groq_parse)
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    act = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 21,
            "rpe": 7,
            "performed_at": "2026-11-23T06:00:00Z",
        },
    ).json()

    # Build 4x240s @ 4.17 m/s separated by 3x90s @ 2.0 m/s so detect_workout detects intervals
    t_arr: list[int] = []
    d_arr: list[float] = []
    v_arr: list[float] = []
    hr_arr: list[int] = []
    cad_arr: list[int] = []
    cur_t = 0
    cur_d = 0.0
    for rep_idx in range(4):
        for _ in range(240):
            t_arr.append(cur_t)
            d_arr.append(round(cur_d, 2))
            v_arr.append(4.17)
            hr_arr.append(168)
            cad_arr.append(184)
            cur_t += 1
            cur_d += 4.17
        if rep_idx < 3:
            for _ in range(90):
                t_arr.append(cur_t)
                d_arr.append(round(cur_d, 2))
                v_arr.append(2.0)
                hr_arr.append(135)
                cad_arr.append(150)
                cur_t += 1
                cur_d += 2.0
    interval_samples = {"t": t_arr, "d": d_arr, "v": v_arr, "hr": hr_arr, "cad": cad_arr}

    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO activity_telemetry "
                "(activity_id, athlete_id, source, sport, device, hr_profile, laps, timer_events, "
                "workout_steps, samples, hr_peak_30s, auto_detection, auto_summary) "
                "VALUES (:id, :a, 'garmin_fit', 'running', 'fr165', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, "
                "'[]'::jsonb, CAST(:samples AS jsonb), 172, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"id": uuid.UUID(act["id"]), "a": athlete_id, "samples": json.dumps(interval_samples)},
        )

    parsed = client.post(
        f"/activities/{act['id']}/prescription/parse",
        json={"text": "4x1000m @ 4:00/km rest 90s"},
    )
    assert parsed.status_code == 200, parsed.text
    blocks = parsed.json()["prescription"]["blocks"]
    assert len(blocks) >= 1

    saved = client.put(
        f"/activities/{act['id']}/prescription",
        json={
            "raw_text": "4x1000m @ 4:00/km rest 90s",
            "blocks": [
                {
                    "reps": 4,
                    "distance_m": 1000,
                    "targets_s_per_km": [240.0, 240.0, 240.0, 240.0],
                    "rest_s": 90,
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    fetched = client.get(f"/activities/{act['id']}/prescription")
    assert fetched.status_code == 200
    assert fetched.json()["prescription"]["source"] == "athlete_text"

    deleted = client.delete(f"/activities/{act['id']}/prescription")
    assert deleted.status_code == 204


def test_t1_f3_05_fit_telemetry_hr_priority_and_trimp_fallback() -> None:
    """F3/M3 opaque-box contract: parse_fit (resting_hr + workout_rpe), 4-tier HR, and HR_TRIMP fallback."""
    fit_bytes = build_synthetic_fit_bytes(
        duration_seconds=90, base_hr=145, max_hr=165, resting_hr=51, device_max_hr=191, workout_rpe=70
    )
    parsed = parse_fit(fit_bytes)
    assert parsed["sport"] == "running"
    assert parsed["device"] == "fr165"
    assert len(parsed["samples"]["t"]) == 90
    assert len(parsed["laps"]) == 1
    assert parsed["hr_profile"]["resting_hr"] == 51
    assert parsed["hr_profile"]["max_hr"] == 191
    assert parsed["session"]["workout_rpe"] == 70
    assert set(parsed["samples"].keys()) == {"t", "d", "v", "hr", "cad"}
    assert peak_rolling_hr(parsed["samples"], window_s=30) is not None

    # HR_TRIMP fallback when workout_rpe == 0
    fit_no_rpe = build_synthetic_fit_bytes(
        duration_seconds=120, base_hr=152, max_hr=170, resting_hr=52, device_max_hr=192, workout_rpe=0
    )
    parsed_no_rpe = parse_fit(fit_no_rpe)
    assert parsed_no_rpe["session"]["workout_rpe"] == 0
    assert parsed_no_rpe["hr_profile"]["resting_hr"] == 52
    trimp_rpe, trimp_load, trimp_metric = compute_hr_trimp_rpe(
        40.0,
        parsed_no_rpe["session"]["avg_hr"],
        parsed_no_rpe["hr_profile"]["max_hr"],
        parsed_no_rpe["hr_profile"]["resting_hr"],
        sex="female",
    )
    assert trimp_metric == "HR_TRIMP"
    assert 1 <= trimp_rpe <= 10
    assert trimp_load == round(40.0 * trimp_rpe, 2)

    def_rpe, def_load, def_metric = compute_hr_trimp_rpe(30.0, None)
    assert (def_rpe, def_load, def_metric) == (4, 120.0, "DURATION_DEFAULT")

    # 4-tier HR resolution: manual > device > history > age_formula
    hr_manual = resolve_hr_profile(
        manual_max_hr=198, manual_resting_hr=48, device=parsed["hr_profile"],
        history_peak_30s=175, birth_year=1994, on_date=_TODAY,
    )
    assert hr_manual.max_hr == 198 and hr_manual.max_hr_source == "manual"
    hr_device = resolve_hr_profile(
        manual_max_hr=None, manual_resting_hr=None, device=parsed["hr_profile"],
        history_peak_30s=175, birth_year=1994, on_date=_TODAY,
    )
    assert hr_device.max_hr == 191 and hr_device.max_hr_source == "device"
    hr_history = resolve_hr_profile(
        manual_max_hr=None, manual_resting_hr=None, device={},
        history_peak_30s=182, birth_year=1994, on_date=_TODAY,
    )
    assert hr_history.max_hr == 182 and hr_history.max_hr_source == "history"
    hr_age = resolve_hr_profile(
        manual_max_hr=None, manual_resting_hr=None, device={},
        history_peak_30s=None, birth_year=1994, on_date=_TODAY,
    )
    assert hr_age.max_hr == round(208 - 0.7 * (2026 - 1994))
    assert hr_age.max_hr_source == "age_formula"

    bundle = build_synthetic_garmin_gdpr_bundle(days=5)
    assert len(bundle["uds"]) == 5


@requires_db
@pytest.mark.e2e_db
def test_t1_f3_06_garmin_fit_upload_and_wellness_roundtrip_db(
    admin_engine, make_e2e_db_client
) -> None:
    """M3 Contract: /garmin/fit/upload (multipart + JSON HR_TRIMP + zero GPS) & /garmin/wellness/*."""
    import base64

    athlete_id = seed_user(admin_engine, timezone_name="Asia/Taipei", sex="female")
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )

    # 1. Multipart upload with FIT workout_rpe=70 -> SESSION_RPE
    fit_rpe = build_synthetic_fit_bytes(
        duration_seconds=120, base_hr=148, max_hr=166, resting_hr=52, device_max_hr=192, workout_rpe=70
    )
    up_multi = client.post(
        "/garmin/fit/upload",
        files={"file": ("run.fit", fit_rpe, "application/octet-stream")},
        data={"client_mutation_id": str(uuid.uuid4()), "activity_name": "E2E Multipart FIT"},
    )
    assert up_multi.status_code == 200, up_multi.text
    multi_body = up_multi.json()
    assert multi_body["source_metric"] == "SESSION_RPE"
    assert multi_body["rpe"] == 7
    assert multi_body["gps_stored"] is False
    assert multi_body["laps_count"] == 1

    # 2. JSON base64 upload with workout_rpe=0 -> HR_TRIMP fallback + zero-GPS DB persistence
    fit_trimp = build_synthetic_fit_bytes(
        duration_seconds=150, base_hr=156, max_hr=172, resting_hr=52, device_max_hr=192, workout_rpe=0
    )
    up_json = client.post(
        "/garmin/fit/upload",
        json={
            "fit_base64": base64.b64encode(fit_trimp).decode("ascii"),
            "client_mutation_id": str(uuid.uuid4()),
            "activity_name": "E2E TRIMP FIT",
        },
    )
    assert up_json.status_code == 200, up_json.text
    json_body = up_json.json()
    assert json_body["source_metric"] == "HR_TRIMP"
    assert 1 <= json_body["rpe"] <= 10
    assert json_body["gps_stored"] is False

    tele_res = client.get(f"/activities/{json_body['activity_id']}/telemetry")
    assert tele_res.status_code == 200, tele_res.text
    assert tele_res.json()["source"] == "garmin_fit"

    with admin_engine.connect() as conn:
        samples = conn.execute(
            text("SELECT samples FROM activity_telemetry WHERE activity_id = :id"),
            {"id": uuid.UUID(json_body["activity_id"])},
        ).scalar_one()
    assert set(samples.keys()).issubset({"t", "d", "v", "hr", "cad"})

    # 3. Wellness GDPR import -> latest (28-day resting_hr_delta) -> trend
    bundle = build_synthetic_garmin_gdpr_bundle(start_date=date(2026, 11, 10), days=6)
    imp = client.post(
        "/garmin/wellness/import",
        json={"uds": bundle["uds"], "sleep": bundle["sleep"], "source": "garmin_gdpr"},
    )
    assert imp.status_code == 200, imp.text
    assert imp.json() == {"imported_days": 6, "source": "garmin_gdpr"}

    latest = client.get("/garmin/wellness/latest?on_date=2026-11-15")
    assert latest.status_code == 200, latest.text
    lat_body = latest.json()
    assert lat_body["available"] is True
    assert lat_body["wellness"]["local_date"] == "2026-11-15"
    assert lat_body["wellness"]["resting_hr_delta"] is not None

    trend = client.get("/garmin/wellness/trend?days=7&on_date=2026-11-15")
    assert trend.status_code == 200, trend.text
    items = trend.json()["items"]
    assert len(items) == 6
    assert [i["local_date"] for i in items] == sorted(i["local_date"] for i in items)


# ===========================================================================
# F4: Sex-Stratified Thermal Pace & Diurnal Weather Compensation
# ===========================================================================


@requires_db
@pytest.mark.e2e_db
def test_t1_f4_01_profile_patch_updates_and_null_clears_hr_overrides(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine, timezone_name="Asia/Taipei")
    client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})

    updated = client.patch(
        "/profile",
        json={"city": "Taipei", "sex": "female", "max_hr_bpm": 190, "resting_hr_bpm": 52, "birth_year": 1995},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["city"] == "Taipei"
    assert body["sex"] == "female"
    assert body["max_hr_bpm"] == 190

    cleared = client.patch("/profile", json={"max_hr_bpm": None, "resting_hr_bpm": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["max_hr_bpm"] is None
    assert cleared.json()["resting_hr_bpm"] is None


@requires_db
@pytest.mark.e2e_db
def test_t1_f4_02_weather_returns_sex_specific_el_helou_metrics(
    admin_engine, make_e2e_db_client
) -> None:
    female_id = seed_user(admin_engine, city="Taipei", sex="female")
    male_id = seed_user(admin_engine, city="Taipei", sex="male")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at, "
                "sunrise_utc, sunset_utc, utc_offset_seconds) "
                "VALUES ('Taipei', 31.0, 75.0, now(), now(), "
                "'2026-11-22T22:15:00Z', '2026-11-23T09:05:00Z', 28800) "
                "ON CONFLICT (city) DO UPDATE SET temperature_c=31.0, humidity_pct=75.0, fetched_at=now()"
            )
        )

    f_res = make_e2e_db_client(actor_id=str(female_id)).get("/weather").json()
    m_res = make_e2e_db_client(actor_id=str(male_id)).get("/weather").json()
    assert f_res["state"] == "CACHED"
    assert f_res["speed_loss_pct"] is not None
    assert f_res["speed_loss_pct_unadjusted"] is not None
    assert f_res["speed_loss_pct_relative_to_normal"] is not None
    assert f_res["climate_normal_reference_c"] is not None
    assert f_res["speed_loss_pct_unadjusted"] != m_res["speed_loss_pct_unadjusted"]


@requires_db
@pytest.mark.e2e_db
def test_t1_f4_03_weather_returns_time_of_day_estimates(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine, city="Taipei", sex="male")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at, "
                "sunrise_utc, sunset_utc, utc_offset_seconds) "
                "VALUES ('Taipei', 26.0, 70.0, now(), now(), "
                "'2026-11-22T22:15:00Z', '2026-11-23T09:05:00Z', 28800) "
                "ON CONFLICT (city) DO UPDATE SET temperature_c=26.0, fetched_at=now()"
            )
        )
    res = make_e2e_db_client(actor_id=str(athlete_id)).get("/weather").json()
    labels = [slot["label"] for slot in res["time_of_day_estimates"]]
    assert labels == ["morning", "midday", "evening"]


@requires_db
@pytest.mark.e2e_db
def test_t1_f4_04_weather_segment_offsets_preserve_requested_order(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine, city="Taipei", sex="female")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at, "
                "sunrise_utc, sunset_utc, utc_offset_seconds) "
                "VALUES ('Taipei', 27.0, 68.0, now(), now(), "
                "'2026-11-22T22:15:00Z', '2026-11-23T09:05:00Z', 28800) "
                "ON CONFLICT (city) DO UPDATE SET temperature_c=27.0, fetched_at=now()"
            )
        )
    res = make_e2e_db_client(actor_id=str(athlete_id)).get(
        "/weather?segment_offsets_min=0&segment_offsets_min=30&segment_offsets_min=45"
    ).json()
    assert [s["offset_min"] for s in res["segment_estimates"]] == [0.0, 30.0, 45.0]


@requires_db
@pytest.mark.e2e_db
def test_t1_f4_05_weather_degrades_to_climate_normal_when_live_unavailable(
    admin_engine, make_e2e_db_client, monkeypatch
) -> None:
    monkeypatch.setattr("app.routes.weather.fetch_live_weather", lambda _city: None)
    for city in ("Taipei", "Tokyo", "London"):
        aid = seed_user(admin_engine, city=city, sex="male")
        res = make_e2e_db_client(actor_id=str(aid)).get("/weather")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["state"] == "CACHED"
        assert body["temperature_c"] is not None
        assert body["climate_normal_reference_c"] is not None


# ===========================================================================
# F5: Bounded Calibrated XGBoost Training Plan & Scenarios
# ===========================================================================


def test_t1_f5_01_bounded_30_feature_xgboost_ranker_and_personalized_pace(
    monkeypatch,
) -> None:
    """R2 / M2 Contract: 30-feature contract + aligned weights + calibrated XGBoost ranking."""
    from ml.feature_contract import FEATURE_CONTRACT, feature_names

    assert len(FEATURE_CONTRACT) == 30
    weights_path = Path(__file__).resolve().parents[2] / "app" / "ml_models" / "plan_model_weights.json"
    weights_meta = json.loads(weights_path.read_text(encoding="utf-8"))
    assert len(weights_meta["feature_names"]) == 30, (
        f"M2 plan_model_weights.json must align to 30 features, got {len(weights_meta['feature_names'])}"
    )
    assert weights_meta["feature_names"] == list(feature_names())

    ctx = TrainingPlanContext(
        triage_urgency=None,
        observation_days=28,
        acute_load=310.0,
        chronic_load=300.0,
        temperature_c=22.0,
        weather_state="LIVE",
        days_since_last_activity=1.0,
        session_count_7d=4,
        sex="female",
        humidity_pct=65.0,
        baseline_easy_pace_s_per_km=345.0,
        recent_avg_hr_bpm=146.0,
        avg_rpe_7d=5.2,
    )
    candidates = generate_training_plan_candidates(ctx)
    monkeypatch.delenv("PLAN_RANKER_MODE", raising=False)
    ranker = configured_plan_ranker()
    assert isinstance(ranker, MLPlanRanker)

    result = ranker.rank(ctx, candidates)
    assert result.ranker_version == "ml-plan-ranker-xgboost-v1"
    assert result.abstained is False
    assert result.abstention_reason is None
    assert result.confidence is not None and 0.28 <= result.confidence <= 1.0
    assert result.reason_code == "STEADY_STATE"
    assert [c.candidate_id for c in sorted(result.ranked_candidates, key=lambda c: c.candidate_id)] == [
        c.candidate_id for c in sorted(candidates, key=lambda c: c.candidate_id)
    ]
    assert result.feature_coverage == {
        "training_load": True,
        "weather": True,
        "injury_triage": False,
    }
    assert len(result.candidate_scores) == len(candidates)
    assert abs(sum(cs.score for cs in result.candidate_scores) - 1.0) <= 0.01
    assert any("模型主因：" in r for cs in result.candidate_scores for r in cs.rationale), (
        "MLPlanRanker must execute XGBoost booster + TreeSHAP rationale, not fallback"
    )

    pace = pace_range(WorkoutType.EASY_RUN.value, 345.0, 2.0)
    assert pace is not None and len(pace) == 2 and pace[0] <= pace[1]


def test_t1_f5_02_scenario_time_budget_excludes_longer_candidates() -> None:
    req = ScenarioOverrideRequest(available_minutes=30)
    facts = AthleteFacts(
        local_date=_TODAY,
        observation_days=28,
        acute_load=300.0,
        chronic_load=300.0,
        temperature_c=22.0,
        humidity_pct=60.0,
        weather_state="CACHED",
    )
    scenario = resolve_scenario(facts, ScenarioOverride(**req.model_dump()))
    evaluation = evaluate_scenario(scenario)
    assert all(c.duration_minutes <= 30 for c in evaluation.ranked_candidates)
    assert len(evaluation.excluded_by_time_budget) >= 1
    assert any(c.workout_type == WorkoutType.RECOVERY_RUN for c in evaluation.ranked_candidates)


def test_t1_f5_03_hot_scenario_applies_thermal_speed_loss_and_ranking_shift() -> None:
    facts = AthleteFacts(
        local_date=_TODAY,
        observation_days=28,
        acute_load=320.0,
        chronic_load=300.0,
        temperature_c=20.0,
        humidity_pct=60.0,
        weather_state="CACHED",
        sex="female",
        climate_reference_c=20.0,
    )
    cool_eval = evaluate_scenario(resolve_scenario(facts, ScenarioOverride(temperature_c=18.0)))
    hot_eval = evaluate_scenario(resolve_scenario(facts, ScenarioOverride(temperature_c=34.0)))
    assert hot_eval.speed_loss_pct > cool_eval.speed_loss_pct
    assert hot_eval.speed_loss_pct > 0.0


@requires_db
@pytest.mark.e2e_db
def test_t1_f5_04_model_report_returns_real_history_and_leakage_safe_cv(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 40,
            "rpe": 5,
            "performed_at": "2026-11-23T06:00:00Z",
        },
    )
    res = client.get("/training-plan/model-report")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["athlete_history"]["completed_activities"] == 1
    assert body["production_ranker"] == "ml-plan-ranker-xgboost-v1"
    assert body["winner_declared"] is False

    ev = body["evaluation"]
    assert ev["winner_declared"] is False
    assert len(ev["splits"]) >= 1
    assert all(s["gap_actual"] > 2 for s in ev["splits"])

    deployed = body["deployed_model"]
    assert deployed is not None
    assert deployed["model_version"] == "ml-plan-ranker-xgboost-v1"
    assert deployed["schema_version"] == 2
    assert deployed["n_features"] == 30
    assert deployed["best_model_type"] == "xgboost"
    assert deployed["calibration"]["xgboost"]["fitted"] is True
    assert deployed["calibration"]["xgboost"]["calibrator_type"] == "PlattCalibrator"
    assert deployed["calibration"]["logistic_regression"]["fitted"] is True

    results = deployed["results"]
    assert {"deterministic", "logistic_regression", "xgboost", "xgboost_calibrated"}.issubset(results.keys())
    assert results["xgboost"]["mrr"] > results["logistic_regression"]["mrr"] > results["deterministic"]["mrr"]
    assert results["xgboost_calibrated"]["ece"] < results["xgboost"]["ece"]


@requires_db
@pytest.mark.e2e_db
def test_t1_f5_05_guidance_today_caches_once_per_day_and_neutral_fallback(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    first = client.get("/guidance/today?llm_tone_enabled=false")
    assert first.status_code == 200, first.text
    second = client.get("/guidance/today?llm_tone_enabled=true")
    assert second.status_code == 200, second.text
    assert first.json()["computed_at"] == second.json()["computed_at"]
    assert first.json()["tone_variant_id"] == second.json()["tone_variant_id"]


# ===========================================================================
# F6: Deterministic Safety Triage & Injury Guidance
# ===========================================================================


@requires_db
@pytest.mark.e2e_db
def test_t1_f6_01_injury_reports_idempotent_create_and_list(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    payload = {
        "client_mutation_id": str(uuid.uuid4()),
        "has_issue": True,
        "severity_band": "MODERATE",
        "body_part": "knee",
        "free_text": "外測膝蓋下坡後痠痛",
        "reported_at": "2026-11-23T06:00:00Z",
    }
    r1 = client.post("/injury-reports", json=payload)
    r2 = client.post("/injury-reports", json=payload)
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"]
    listed = client.get("/injury-reports").json()
    assert len(listed["items"]) == 1
    assert listed["items"][0]["free_text"] == "外測膝蓋下坡後痠痛"


def test_t1_f6_02_safety_triage_emergency_red_flags_block_running() -> None:
    decision = assess_safety_triage(
        make_safety_triage_input(
            severity_band="MILD",
            body_part="chest",
            chest_pain_or_breathing_difficulty=True,
        )
    )
    assert decision.urgency == TriageUrgency.EMERGENCY
    assert decision.running_allowed is False
    assert decision.rule_version == SAFETY_RULE_VERSION
    assert "RED_FLAG_CARDIORESPIRATORY" in decision.matched_rule_ids

    text_decision = assess_safety_triage_text(
        severity_band=None, body_part=None, message="跑步時胸痛快昏倒了"
    )
    assert text_decision is not None
    assert text_decision.urgency == TriageUrgency.EMERGENCY
    assert text_decision.running_allowed is False


def test_t1_f6_03_safety_triage_prompt_clinician_conditions() -> None:
    for kwargs in (
        {"unable_to_bear_weight": True, "severity_band": "MILD"},
        {"localized_bone_pain_worse_with_weight_bearing": True, "severity_band": "MILD"},
        {"severity_band": "SEVERE"},
    ):
        decision = assess_safety_triage(make_safety_triage_input(body_part="shin", **kwargs))
        assert decision.urgency == TriageUrgency.PROMPT_CLINICIAN
        assert decision.running_allowed is False


def test_t1_f6_04_injury_guidance_mild_moderate_returns_self_care_with_citations() -> None:
    passage = EvidencePassage(
        evidence_id="ev-calf-01",
        title="Calf Strain Load Management",
        publisher="BJSM",
        source_url="https://example.org/ev-calf-01",
        revision_date="2025-01-01",
        license_or_provenance="reviewed",
        corpus_version="sports-medicine-v1",
        text="Monitor morning stiffness and reduce impact volume.",
    )

    class _Provider:
        provider_name = "stub-llm"

        def generate(self, payload: dict) -> dict:
            return {
                "summary": "小腿緊繃先暫停跑步並觀察 48 小時。",
                "next_steps": ["暫停速度訓練", "觀察隔天晨起緊繃感"],
                "citation_ids": ["ev-calf-01"],
            }

    triage = assess_safety_triage(make_safety_triage_input(severity_band="MILD", body_part="calf"))
    out = compose_injury_guidance(triage, (passage,), _Provider())
    assert out.urgency == TriageUrgency.SELF_CARE_NEXT_STEP
    assert out.running_allowed is False
    assert out.used_fallback is False
    assert len(out.citations) == 1
    assert out.citations[0].evidence_id == "ev-calf-01"


@requires_db
@pytest.mark.e2e_db
def test_t1_f6_05_guidance_library_filters_without_injury_report(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(actor_id=str(athlete_id))
    res = client.get("/guidance/library?limit=5")
    assert res.status_code == 200, res.text
    assert "passages" in res.json()


# ===========================================================================
# F7: ReAct Health Coach, Grounded Streaming & Proposals
# ===========================================================================


def test_t1_f7_01_react_coach_executes_multi_step_tools_and_preserves_contract() -> None:
    """R3 / M5 Contract: Unified ReAct coach executes multi-step tools and populates enriched context."""
    assert {"triage_urgency", "running_allowed", "agent_trace", "media_asset"}.issubset(
        CoachChatResponse.model_fields
    ), "M5 CoachChatResponse must expose top-level triage_urgency, running_allowed, agent_trace, media_asset"

    captured_ctx: dict[str, object] = {}

    def _scripted_llm(msgs: list[dict[str, str]], enriched_ctx: dict[str, object]) -> tuple[str, str]:
        captured_ctx.update(enriched_ctx)
        return ("綜合 ACWR 1.07、氣溫 33°C 與恢復指標，建議今日 20 分鐘恢復跑。", "MODEL")

    outcome = run_unified_react_coach(
        question="氣溫 33 度，看我的 Garmin HRV 睡眠恢復、熱天配速和今天課表建議",
        surface_profile="private_guidance",
        context={
            "acute_load": 320.0,
            "chronic_load": 300.0,
            "load_ratio": 1.07,
            "observation_days": 28,
            "temperature": 33.0,
            "humidity": 75.0,
            "climate_reference_c": 25.0,
            "sex": "female",
            "wellness": {
                "resting_hr_bpm": 54,
                "resting_hr_delta": 4.0,
                "hrv_ms": 48.0,
                "hrv_status": "LOW",
                "sleep_hours": 6.2,
                "body_battery_recent": 45,
            },
            "plan_evaluation": {
                "ranker_version": "ml-plan-ranker-xgboost-v1",
                "abstained": False,
                "candidates": [
                    {
                        "workout_type": "RECOVERY_RUN",
                        "duration_minutes": 20,
                        "distance_km": 3.0,
                    }
                ],
            },
        },
        llm_complete_fn=_scripted_llm,
    )

    assert outcome.answer_source == "MODEL"
    assert outcome.triage_urgency is None
    assert outcome.running_allowed is True
    assert [s.action for s in outcome.trace] == [
        "observe_athlete_status",
        "get_wellness_baseline",
        "compute_heat_pace",
        "evaluate_training_plan",
    ]
    assert "1.07" in outcome.trace[0].observation
    assert "54" in outcome.trace[1].observation
    assert "El Helou" in outcome.trace[2].observation
    assert "RECOVERY_RUN" in outcome.trace[3].observation
    assert "react_observations" in captured_ctx
    assert "33" in str(captured_ctx["react_observations"])


@requires_db
@pytest.mark.e2e_db
def test_t1_f7_02_guidance_chat_stream_emits_steps_deltas_proposal_and_done(
    admin_engine, make_e2e_db_client, scripted_coach_provider
) -> None:
    athlete_id = seed_user(admin_engine)
    scripted_coach_provider(
        answer_text="今天可以先進行 30 分鐘輕鬆跑。",
        json_override={"available_minutes": 30},
    )

    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    res = client.post(
        "/guidance/chat/stream",
        json={"messages": [{"role": "user", "content": "今天只有 30 分鐘"}]},
    )
    assert res.status_code == 200
    assert res.text.strip().endswith("data: [DONE]")
    events = parse_sse_events(res.text)
    assert [e["step"] for e in events if "step" in e] == [
        "READ_TRAINING_LOAD",
        "REVIEWED_GUIDANCE",
        "CONSIDERED_OPTIONS",
    ]
    assert "".join(e["delta"] for e in events if "delta" in e) == "今天可以先進行 30 分鐘輕鬆跑。"
    assert any("proposal" in e for e in events)


@requires_db
@pytest.mark.e2e_db
def test_t1_f7_03_proposal_accept_applies_to_training_plan_today(
    admin_engine, make_e2e_db_client, scripted_coach_provider
) -> None:
    athlete_id = seed_user(admin_engine)
    scripted_coach_provider(
        answer_text="今天可以先進行 25 分鐘輕鬆跑。",
        json_override={"available_minutes": 25},
    )

    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    res = client.post(
        "/guidance/chat/stream",
        json={"messages": [{"role": "user", "content": "只有 25 分鐘"}]},
    )
    proposal = [e["proposal"] for e in parse_sse_events(res.text) if "proposal" in e][0]
    assert proposal["accepted"] is False

    accepted = client.post(f"/guidance/proposals/{proposal['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["applied"] is True

    plan = client.get("/training-plan/today").json()
    assert all(c["duration_minutes"] <= 25 for c in plan["candidates"])


@requires_db
@pytest.mark.e2e_db
def test_t1_f7_04_proposal_dismiss_and_list_history(
    admin_engine, make_e2e_db_client, scripted_coach_provider
) -> None:
    athlete_id = seed_user(admin_engine)
    scripted_coach_provider(
        answer_text="今天可以先進行 20 分鐘輕鬆跑。",
        json_override={"available_minutes": 20},
    )

    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    res = client.post(
        "/guidance/chat/stream",
        json={"messages": [{"role": "user", "content": "只有 20 分鐘"}]},
    )
    proposal = [e["proposal"] for e in parse_sse_events(res.text) if "proposal" in e][0]

    dismissed = client.post(f"/guidance/proposals/{proposal['id']}/dismiss")
    assert dismissed.status_code == 200, dismissed.text
    listed = client.get("/guidance/proposals").json()
    assert any(p["id"] == proposal["id"] for p in listed["proposals"])


def test_t1_f7_05_healthz_providers_unauthenticated_no_credentials(
    make_no_db_client,
) -> None:
    client = make_no_db_client(actor_id=None)
    res = client.get("/healthz/providers")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "status" in body or "provider" in body or "configured" in body
    raw_text = res.text.lower()
    assert "api_key" not in raw_text and "secret" not in raw_text


@requires_db
@pytest.mark.e2e_db
def test_t1_f7_06_guidance_chat_http_react_endpoint_db(
    admin_engine, make_e2e_db_client, scripted_coach_provider
) -> None:
    """R3 / M5 Contract: POST /guidance/chat exercises real route + ReAct loop via external CoachProvider."""
    athlete_id = seed_user(admin_engine, city="Taipei", sex="female")
    scripted_coach_provider(
        answer_text="今天只有 30 分鐘，建議進行恢復跑。",
        json_override={"available_minutes": 30},
    )
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    res = client.post(
        "/guidance/chat",
        json={"messages": [{"role": "user", "content": "今天只有 30 分鐘，看我的負荷與高溫配速建議"}]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer_source"] == "MODEL"
    assert body["triage_urgency"] is None
    assert body["running_allowed"] is True
    assert len(body["agent_trace"]) >= 2
    assert body["proposal"]["facts"]["available_minutes"] == 30


# ===========================================================================
# F8: Team Consent Governance, Roster, @AI Chat & Coach Cards
# ===========================================================================


@requires_db
@pytest.mark.e2e_db
def test_t1_f8_01_accept_invite_and_grant_consent_surfaces_roster_fields(
    admin_engine, make_e2e_db_client
) -> None:
    coach_id = seed_user(admin_engine, display_name="Coach A")
    athlete_id = seed_user(admin_engine, display_name="Runner A")
    team_id = seed_team_and_members(
        admin_engine, coach_id=coach_id, athlete_id=athlete_id, athlete_status="INVITED"
    )

    ath_client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    acc = ath_client.patch(f"/me/team-memberships/{team_id}", json={"action": "accept"})
    assert acc.status_code == 200 and acc.json()["status"] == "ACTIVE"
    for scope in ("activity_summary", "training_load"):
        g = ath_client.patch(f"/me/consent-grants/{scope}", json={"team_id": str(team_id), "granted": True})
        assert g.status_code == 200 and g.json()["granted"] is True

    ath_client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 40,
            "rpe": 5,
            "performed_at": "2026-11-23T06:00:00Z",
        },
    )

    coach_client = make_e2e_db_client(actor_id=str(coach_id))
    roster = coach_client.get(f"/teams/{team_id}/roster").json()
    row = roster["items"][0]
    assert row["last_activity_local_date"] == "2026-11-23"
    assert row["acute_load_au"] is not None
    assert row["injury_has_issue"] is None  # injury_status not granted


@requires_db
@pytest.mark.e2e_db
def test_t1_f8_02_team_athlete_activities_respects_activity_summary_consent(
    admin_engine, make_e2e_db_client
) -> None:
    coach_id = seed_user(admin_engine)
    athlete_id = seed_user(admin_engine)
    team_id = seed_team_and_members(
        admin_engine, coach_id=coach_id, athlete_id=athlete_id, consent_scopes=("activity_summary",)
    )
    ath_client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    kept = ath_client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 35,
            "rpe": 5,
            "performed_at": "2026-11-23T06:00:00Z",
        },
    ).json()
    deleted = ath_client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 20,
            "rpe": 4,
            "performed_at": "2026-11-23T08:00:00Z",
        },
    ).json()
    ath_client.delete(f"/activities/{deleted['id']}")

    acts = make_e2e_db_client(actor_id=str(coach_id)).get(
        f"/teams/{team_id}/athletes/{athlete_id}/activities?local_date=2026-11-23"
    )
    assert acts.status_code == 200, acts.text
    assert [i["id"] for i in acts.json()["items"]] == [kept["id"]]


@requires_db
@pytest.mark.e2e_db
def test_t1_f8_03_coach_ai_schedule_card_edit_confirm_and_batch_revoke(
    admin_engine, make_e2e_db_client, patch_chat_test_engine, scripted_groq_transport
) -> None:
    def _groq_schedule_handler(body: dict[str, object]) -> dict[str, object]:
        msgs = body.get("messages") or []
        sys_txt = str((msgs[0] if msgs else {}).get("content") or "")
        if "允許的 intent" in sys_txt:
            return {"intent": "schedule"}
        return {
            "days": [
                {
                    "source": "幫選手排明天 30 分鐘輕鬆跑",
                    "relative": "明天",
                    "items": [
                        {
                            "type": "run",
                            "kind": "easy",
                            "title": "輕鬆跑",
                            "variants": {"all": [{"reps": 1, "duration_s": 1800}]},
                        }
                    ],
                }
            ]
        }

    scripted_groq_transport(_groq_schedule_handler)
    coach_id = seed_user(admin_engine, display_name="Coach Card")
    athlete_id = seed_user(admin_engine, display_name="Runner Card")
    seed_team_and_members(
        admin_engine, coach_id=coach_id, athlete_id=athlete_id, consent_scopes=("training_load",)
    )
    coach_client = make_e2e_db_client(actor_id=str(coach_id))
    ath_client = make_e2e_db_client(actor_id=str(athlete_id))
    rooms = coach_client.get("/chat/rooms").json()["rooms"]
    direct_room = [r for r in rooms if r["kind"] == "direct"][0]

    sent = coach_client.post(
        f"/chat/rooms/{direct_room['id']}/messages",
        json={"body": "@AI 幫選手排明天 30 分鐘輕鬆跑"},
    )
    assert sent.status_code == 201

    msgs = coach_client.get(f"/chat/rooms/{direct_room['id']}/messages").json()
    plan_cards = [c for c in msgs["cards"] if c["kind"] == "plan"]
    assert plan_cards, "Coach @AI schedule should produce a coach-owned plan card"
    card = plan_cards[0]

    # Athlete must NOT see coach's plan card
    ath_msgs = ath_client.get(f"/chat/rooms/{direct_room['id']}/messages").json()
    assert ath_msgs["cards"] == []

    confirmed = coach_client.post(f"/chat/cards/{card['id']}/confirm-plan", json={})
    assert confirmed.status_code == 200, confirmed.text
    batch_id = confirmed.json().get("batch_id")
    assert batch_id, f"confirm-plan must return non-empty batch_id: {confirmed.json()}"
    revoked = coach_client.post(f"/chat/batches/{batch_id}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["removed"] >= 1


@requires_db
@pytest.mark.e2e_db
def test_t1_f8_04_coach_ai_data_query_and_schedule_draft(
    admin_engine, make_e2e_db_client, patch_chat_test_engine, scripted_groq_transport
) -> None:
    from zoneinfo import ZoneInfo

    def _groq_data_handler(body: dict[str, object]) -> dict[str, object]:
        msgs = body.get("messages") or []
        sys_txt = str((msgs[0] if msgs else {}).get("content") or "")
        user_txt = str((msgs[-1] if msgs else {}).get("content") or "")
        if "允許的 intent" in sys_txt:
            return {"intent": "data"}
        if "Action: observe_athlete_status" not in user_txt:
            return {"thought": "先觀測選手訓練負荷與活動狀態", "action": "observe_athlete_status"}
        return {"thought": "產生今日課表建議", "action": "recommend_workout_plan"}

    scripted_groq_transport(_groq_data_handler)
    coach_id = seed_user(admin_engine, display_name="Coach Data")
    athlete_id = seed_user(admin_engine, display_name="Runner Data")
    seed_team_and_members(
        admin_engine, coach_id=coach_id, athlete_id=athlete_id, consent_scopes=("training_load",)
    )
    now_utc = datetime.now(timezone.utc)
    taipei_tz = ZoneInfo("Asia/Taipei")
    today_taipei = now_utc.astimezone(taipei_tz).date()
    ath_client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    coach_client = make_e2e_db_client(actor_id=str(coach_id))

    # Seed 7 earlier runs (8..20 days ago) + 1 run today so observation_days >= 7
    # (preventing cold-start abstention to REST_DAY) while keeping sessions_7d == 1.
    for days_ago in (*range(20, 6, -2), 0):
        local_dt = datetime.combine(
            today_taipei - timedelta(days=days_ago),
            datetime.min.time(),
            tzinfo=taipei_tz,
        ).replace(hour=6)
        act_res = ath_client.post(
            "/activities",
            json={
                "client_mutation_id": str(uuid.uuid4()),
                "duration_minutes": 40,
                "rpe": 5,
                "performed_at": local_dt.astimezone(timezone.utc).isoformat(),
            },
        )
        assert act_res.status_code == 201, act_res.text

    rooms = coach_client.get("/chat/rooms").json()["rooms"]
    direct_room = [r for r in rooms if r["kind"] == "direct"][0]

    draft = coach_client.post(f"/chat/rooms/{direct_room['id']}/schedule-draft", json={})
    assert draft.status_code == 201, draft.text
    assert draft.json()["kind"] == "plan"

    sent = coach_client.post(
        f"/chat/rooms/{direct_room['id']}/messages",
        json={"body": "@AI 看一下選手最近訓練負荷並建議今天課表"},
    )
    assert sent.status_code == 201
    sent_id = sent.json()["id"]

    msgs: dict[str, object] = {}
    for _ in range(5):
        msgs = coach_client.get(f"/chat/rooms/{direct_room['id']}/messages").json()
        user_msg = next((m for m in msgs["messages"] if m["id"] == sent_id), None)
        if user_msg and user_msg.get("ai_state") != "pending":
            break

    user_msg = next(m for m in msgs["messages"] if m["id"] == sent_id)
    assert user_msg["ai_state"] == "done"

    ai_replies = [
        m
        for m in msgs["messages"]
        if m["sender_kind"] == "ai" and (m.get("payload") or {}).get("reply_to") == sent_id
    ]
    assert len(ai_replies) == 1
    ai_reply = ai_replies[0]
    assert [s["action"] for s in ai_reply["payload"]["react_trace"]] == [
        "observe_athlete_status",
        "recommend_workout_plan",
    ]
    assert "【狀態觀測】" in ai_reply["body"]
    assert "近 7 天完成 1 次訓練" in ai_reply["body"]
    assert "【課表建議】" in ai_reply["body"]

    card_id = ai_reply["payload"]["card_id"]
    coach_plan_cards = [c for c in msgs["cards"] if c["id"] == card_id and c["kind"] == "plan"]
    assert len(coach_plan_cards) == 1
    ath_msgs = ath_client.get(f"/chat/rooms/{direct_room['id']}/messages").json()
    assert ath_msgs["cards"] == []


@requires_db
@pytest.mark.e2e_db
def test_t1_f8_05_athlete_ai_body_report_confirm_and_retract(
    admin_engine, make_e2e_db_client, patch_chat_test_engine
) -> None:
    coach_id = seed_user(admin_engine)
    athlete_id = seed_user(admin_engine)
    seed_team_and_members(admin_engine, coach_id=coach_id, athlete_id=athlete_id)

    ath_client = make_e2e_db_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"})
    rooms = ath_client.get("/chat/rooms").json()["rooms"]
    direct_room = [r for r in rooms if r["kind"] == "direct"][0]

    sent = ath_client.post(
        f"/chat/rooms/{direct_room['id']}/messages",
        json={"body": "@AI 我今天左腳膝蓋骨頭痛、踩地更痛，疼痛 5 分"},
    )
    assert sent.status_code == 201
    msg_id = sent.json()["id"]

    msgs = ath_client.get(f"/chat/rooms/{direct_room['id']}/messages").json()
    cards = [c for c in msgs["cards"] if c["kind"] == "body_report"]
    assert cards, "Athlete @AI body report should produce a body_report card"
    if not cards[0]["payload"].get("severity_band"):
        edited = ath_client.put(
            f"/chat/cards/{cards[0]['id']}",
            json={"body_part": "knee", "severity_band": "MODERATE"},
        )
        assert edited.status_code == 200, edited.text

    confirmed = ath_client.post(f"/chat/cards/{cards[0]['id']}/confirm-report")
    assert confirmed.status_code == 200, confirmed.text
    assert len(ath_client.get("/injury-reports").json()["items"]) == 1

    retracted = ath_client.post(f"/chat/messages/{msg_id}/retract")
    assert retracted.status_code == 204


# ===========================================================================
# F9: Multimedia Health Education Output & Zero-API Fallback
# ===========================================================================


def test_t1_f9_01_guidance_media_returns_valid_png_json_and_binary(
    make_no_db_client,
) -> None:
    client = make_no_db_client(actor_id=str(uuid.uuid4()))
    payload = {
        "topic": "Achilles Tendon Load Management",
        "body_part": "Achilles",
        "triage_urgency": "SELF_CARE_NEXT_STEP",
        "running_allowed": False,
        "guidance_summary": "Reduce high-impact load and monitor morning stiffness.",
        "next_steps": ["Pause speed work", "Track pain 24h"],
        "citations": ["BJSM Tendinopathy Consensus"],
        "media_format": "png",
        "athlete_context": {"acwr": 1.35, "temperature_c": 30.0},
    }
    res_json = client.post("/guidance/media", json=payload)
    assert res_json.status_code == 200, res_json.text
    body = res_json.json()
    assert body["media_format"] == "png"
    assert body["mime_type"] == "image/png"
    png_bytes = decode_media_response_bytes(body)
    w, h = assert_valid_png(png_bytes)
    assert (w, h) == (800, 500)

    res_bin = client.post("/guidance/media?response_mode=binary", json=payload)
    assert res_bin.status_code == 200
    assert res_bin.headers["content-type"] == "image/png"
    assert_valid_png(res_bin.content)


def test_t1_f9_02_guidance_media_returns_valid_svg_with_topic_and_citations(
    make_no_db_client,
) -> None:
    client = make_no_db_client(actor_id=str(uuid.uuid4()))
    res = client.post(
        "/guidance/media",
        json={
            "topic": "Runner Knee Patellofemoral Guide",
            "body_part": "knee",
            "triage_urgency": "PROMPT_CLINICIAN",
            "running_allowed": False,
            "guidance_summary": "Stop running if pain sharpens on stairs and consult a clinician.",
            "next_steps": ["Rest from downhill running", "Schedule clinical evaluation"],
            "citations": ["ACSM Patellofemoral Guide 2024"],
            "media_format": "svg",
        },
    )
    assert res.status_code == 200, res.text
    svg_bytes = decode_media_response_bytes(res.json())
    root = assert_valid_svg(svg_bytes)
    svg_text = svg_bytes.decode("utf-8")
    assert root.attrib["width"] == "800"
    assert "Runner Knee Patellofemoral Guide" in svg_text
    assert "ACSM Patellofemoral Guide 2024" in svg_text
    assert "PROMPT CLINICIAN" in svg_text


@pytest.mark.e2e_slow
def test_t1_f9_03_guidance_media_returns_valid_mp4_via_ffmpeg(
    make_no_db_client, tmp_path
) -> None:
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin, "ffmpeg must be installed in test environment for MP4 rendering verification"
    client = make_no_db_client(actor_id=str(uuid.uuid4()))
    res = client.post(
        "/guidance/media/render",
        json={
            "topic": "Heat Exhaustion Prevention",
            "body_part": "systemic",
            "triage_urgency": "SELF_CARE_NEXT_STEP",
            "running_allowed": False,
            "guidance_summary": "Hydrate early and shift runs away from midday heat.",
            "next_steps": ["Hydrate with electrolytes", "Run before sunrise"],
            "citations": ["El Helou 2012"],
            "media_format": "mp4",
        },
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "video/mp4"
    assert res.headers["x-generator-mode"] == "local_ffmpeg"
    assert_valid_mp4(res.content)

    mp4_path = tmp_path / "e2e_card.mp4"
    mp4_path.write_bytes(res.content)
    decode = subprocess.run(
        [ffmpeg_bin, "-v", "error", "-i", str(mp4_path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert decode.returncode == 0, f"ffmpeg full frame decode failed: {decode.stderr}"
    assert decode.stderr.strip() == "", f"ffmpeg emitted decode errors: {decode.stderr}"


def test_t1_f9_04_guidance_media_succeeds_with_zero_external_api_keys(
    make_no_db_client, no_external_apis
) -> None:
    client = make_no_db_client(actor_id=str(uuid.uuid4()))
    for fmt, expected_modes in (
        ("png", {"local_raster"}),
        ("svg", {"local_svg_fallback"}),
    ):
        res = client.post(
            "/guidance/media",
            json={
                "topic": "Zero Key Local Render",
                "guidance_summary": "Local rendering operates deterministically without external keys.",
                "media_format": fmt,
            },
        )
        assert res.status_code == 200
        assert res.json()["generator_mode"] in expected_modes


def test_t1_f9_05_react_coach_invokes_multimedia_tool_when_requested(
    no_external_apis,
) -> None:
    """R4 / M5 Contract: ReAct health coach executes generate_health_media for PNG and MP4/SVG."""
    png_outcome = run_unified_react_coach(
        question="我小腿痠痛，請幫我產生衛教圖卡 PNG",
        surface_profile="private_guidance",
        context={
            "body_part": "calf",
            "severity_band": "MILD",
            "acute_load": 320.0,
            "chronic_load": 250.0,
            "load_ratio": 1.28,
            "temperature": 29.0,
            "rag_passages": [
                {
                    "title": "Calf Load Mgmt",
                    "publisher": "BJSM",
                    "source_url": "https://example.org/calf",
                }
            ],
        },
        llm_complete_fn=lambda msgs, ctx: ("已為您生成小腿負荷管理衛教圖卡。", "MODEL"),
    )
    assert "generate_health_media" in [s.action for s in png_outcome.trace]
    assert png_outcome.media_asset is not None
    assert png_outcome.media_asset["media_format"] == "png"
    assert png_outcome.media_asset["mime_type"] == "image/png"
    assert png_outcome.media_asset["generator_mode"] == "local_raster"
    assert png_outcome.media_asset["file_size_bytes"] > 0
    assert png_outcome.media_asset["asset_id"].startswith("hm_")
    assert png_outcome.rag_citations[0]["publisher"] == "BJSM"

    mp4_outcome = run_unified_react_coach(
        question="我膝蓋劇痛無法承重，請給我衛教影片 mp4",
        surface_profile="private_guidance",
        context={"body_part": "knee", "severity_band": "SEVERE"},
        llm_complete_fn=None,
    )
    assert mp4_outcome.triage_urgency == "PROMPT_CLINICIAN"
    assert mp4_outcome.running_allowed is False
    trace_actions = [s.action for s in mp4_outcome.trace]
    assert "evaluate_training_plan" in trace_actions
    assert "generate_health_media" in trace_actions
    assert mp4_outcome.media_asset is not None
    assert mp4_outcome.media_asset["triage_urgency"] == "PROMPT_CLINICIAN"
    assert mp4_outcome.media_asset["file_size_bytes"] > 0
    assert mp4_outcome.media_asset["asset_id"].startswith("hm_")
    if shutil.which("ffmpeg"):
        assert mp4_outcome.media_asset["media_format"] == "mp4"
        assert mp4_outcome.media_asset["mime_type"] == "video/mp4"
        assert mp4_outcome.media_asset["generator_mode"] == "local_ffmpeg"
    else:
        assert mp4_outcome.media_asset["media_format"] == "svg"
        assert mp4_outcome.media_asset["mime_type"] == "image/svg+xml"
    assert "REST_AND_SEEK_CARE" in mp4_outcome.reply_text
    assert "不得推薦跑步課表" in mp4_outcome.reply_text

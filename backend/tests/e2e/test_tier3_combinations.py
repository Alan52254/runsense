"""Tier 3 E2E tests: 9 pairwise cross-feature combination tests (T3-01..T3-09)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import text

from app.fit_telemetry import parse_fit
from app.garmin_ingest import compute_hr_trimp_rpe
from app.health_guidance_service import configured_guidance_provider
from app.injury_guidance import EvidencePassage, compose_injury_guidance
from app.plan_ranking import MLPlanRanker
from app.react_coach import AgentSecurityEnvelope, run_unified_react_coach
from app.safety_triage import SafetyTriageInput, TriageUrgency, assess_safety_triage, assess_safety_triage_text
from app.training_plan_candidates import TrainingPlanContext, generate_training_plan_candidates

from tests.e2e.conftest import (
    _get_connection_as_runtime_role,
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

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_tier3]

_FIXED_UTC = datetime(2026, 11, 23, 8, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 11, 23)


@requires_db
@pytest.mark.e2e_db
def test_t3_01_f2_x_f5_activity_create_and_soft_delete_updates_plan_and_model_report(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine, city="Taipei", sex="male")
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    kept = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 40,
            "rpe": 5,
            "performed_at": "2026-11-22T06:00:00Z",
            "distance_km": 7.0,
        },
    ).json()
    ghost = client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 60,
            "rpe": 8,
            "performed_at": "2026-11-23T06:00:00Z",
            "distance_km": 12.0,
        },
    ).json()
    assert kept["id"] != ghost["id"]
    client.delete(f"/activities/{ghost['id']}")

    report = client.get("/training-plan/model-report").json()
    assert report["athlete_history"]["completed_activities"] == 1

    plan = client.get("/training-plan/today").json()
    assert plan["inputs"]["session_count_7d"] == 1


@requires_db
@pytest.mark.e2e_db
def test_t3_02_f2_x_f8_soft_delete_removes_activity_from_team_roster_and_ai_agent(
    admin_engine, make_e2e_db_client
) -> None:
    coach_id = seed_user(admin_engine)
    athlete_id = seed_user(admin_engine)
    team_id = seed_team_and_members(
        admin_engine,
        coach_id=coach_id,
        athlete_id=athlete_id,
        consent_scopes=("activity_summary", "training_load"),
    )
    ath_client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    act = ath_client.post(
        "/activities",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "duration_minutes": 45,
            "rpe": 6,
            "performed_at": "2026-11-23T06:00:00Z",
        },
    ).json()
    ath_client.delete(f"/activities/{act['id']}")

    coach_client = make_e2e_db_client(actor_id=str(coach_id))
    roster = coach_client.get(f"/teams/{team_id}/roster").json()["items"][0]
    assert roster["last_activity_local_date"] is None
    acts = coach_client.get(
        f"/teams/{team_id}/athletes/{athlete_id}/activities?local_date=2026-11-23"
    ).json()
    assert acts["items"] == []

    from app import chat_agent

    with admin_engine.begin() as conn:
        status = chat_agent.observe_athlete_status(conn, athlete_id, today=_TODAY)
    assert status["sessions_7d"] == 0


@requires_db
@pytest.mark.e2e_db
def test_t3_03_f4_x_f5_profile_weather_propagates_to_plan_evaluate(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine, city="Taipei", sex="female")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at, "
                "sunrise_utc, sunset_utc, utc_offset_seconds) "
                "VALUES ('Taipei', 32.0, 80.0, now(), now(), "
                "'2026-11-22T22:15:00Z', '2026-11-23T09:05:00Z', 28800) "
                "ON CONFLICT (city) DO UPDATE SET temperature_c=32.0, humidity_pct=80.0, fetched_at=now()"
            )
        )
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    weather = client.get("/weather").json()
    assert weather["city"] == "Taipei"

    eval_res = client.post("/training-plan/evaluate", json={}).json()
    assert eval_res["inputs"]["temperature_c"] == 32.0
    assert eval_res["scenario"]["speed_loss_pct"] > 0.0


@requires_db
@pytest.mark.e2e_db
def test_t3_04_f6_x_f5_severe_injury_locks_plan_today_and_evaluate(
    admin_engine, make_e2e_db_client
) -> None:
    athlete_id = seed_user(admin_engine)
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    client.post(
        "/injury-reports",
        json={
            "client_mutation_id": str(uuid.uuid4()),
            "has_issue": True,
            "severity_band": "SEVERE",
            "body_part": "shin",
            "free_text": "單腳跳就劇痛",
            "reported_at": "2026-11-23T06:00:00Z",
        },
    )

    today_plan = client.get("/training-plan/today").json()
    assert [c["workout_type"] for c in today_plan["candidates"]] == ["REST_AND_SEEK_CARE"]
    assert today_plan["candidates"][0]["running_allowed"] is False

    override_plan = client.post(
        "/training-plan/evaluate",
        json={"available_minutes": 90, "reported_severity_band": "MILD"},
    ).json()
    assert [c["workout_type"] for c in override_plan["candidates"]] == ["REST_AND_SEEK_CARE"]
    assert override_plan["candidates"][0]["running_allowed"] is False


def test_t3_05_f6_x_f7_red_flag_text_locks_react_security_envelope() -> None:
    """F6 x F7 (M5 Contract): Red-flag text triggers deterministic EMERGENCY preserved through ReAct loop."""
    triage = assess_safety_triage_text(
        severity_band=None, body_part=None, message="今天跑步胸痛快昏倒"
    )
    assert triage is not None
    assert triage.urgency == TriageUrgency.EMERGENCY
    assert triage.running_allowed is False

    env = AgentSecurityEnvelope.from_inputs(message="今天跑步胸痛快昏倒", recorded_urgency=None)
    assert env.triage_urgency == TriageUrgency.EMERGENCY
    assert env.running_allowed is False

    outcome = run_unified_react_coach(
        question="今天跑步胸痛快昏倒",
        envelope=env,
        llm_complete_fn=lambda msgs, ctx: ("你可以去跑 10 公里。", "MODEL"),
    )
    assert outcome.triage_urgency == "EMERGENCY"
    assert outcome.running_allowed is False
    assert "立即停止跑步" in outcome.reply_text


@requires_db
@pytest.mark.e2e_db
def test_t3_06_f7_x_f8_shared_proposal_declined_by_coach_and_assigned_day_blocks_accept(
    admin_engine, make_e2e_db_client, scripted_coach_provider
) -> None:
    coach_id = seed_user(admin_engine)
    athlete_id = seed_user(admin_engine)
    team_id = seed_team_and_members(admin_engine, coach_id=coach_id, athlete_id=athlete_id)

    scripted_coach_provider(answer_text="好", json_override={"available_minutes": 30})

    ath_client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    coach_client = make_e2e_db_client(actor_id=str(coach_id))

    stream = ath_client.post(
        "/guidance/chat/stream",
        json={"messages": [{"role": "user", "content": "我今天只有 30 分鐘"}]},
    )
    proposal = [e["proposal"] for e in parse_sse_events(stream.text) if "proposal" in e][0]
    shared = ath_client.post(f"/guidance/proposals/{proposal['id']}/share")
    assert shared.status_code == 200, shared.text

    rooms = coach_client.get("/chat/rooms").json()["rooms"]
    direct_room = [r for r in rooms if r["kind"] == "direct"][0]
    coach_msgs = coach_client.get(f"/chat/rooms/{direct_room['id']}/messages").json()["messages"]
    suggestion_msgs = [
        m for m in coach_msgs if (m.get("payload") or {}).get("kind") == "coach_suggestion"
    ]
    assert suggestion_msgs, "Sharing proposal with coach must create a coach_suggestion message in direct room"
    declined = coach_client.post(
        f"/chat/messages/{suggestion_msgs[-1]['id']}/decline-suggestion",
        json={"reason": "按原定課表調整即可"},
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["decision"] == "declined"

    coach_client.post(
        f"/teams/{team_id}/assignments",
        json={
            "athlete_id": str(athlete_id),
            "local_date": "2026-11-23",
            "title": "Team Easy",
            "duration_minutes": 40,
            "intensity_label": "Easy",
        },
    )
    accept = ath_client.post(f"/guidance/proposals/{proposal['id']}/accept").json()
    assert accept["applied"] is False
    assert accept["reason"] == "COACH_SCHEDULED"


@requires_db
@pytest.mark.e2e_db
def test_t3_07_f1_x_f8_demo_login_mfa_session_revocation_blocks_subsequent_calls(
    admin_engine, make_e2e_demo_client
) -> None:
    coach_id = seed_user(admin_engine, email="t3-07-coach@runsense.e2e", password="DemoPass!2026")
    athlete_id = seed_user(admin_engine)
    team_id = seed_team_and_members(admin_engine, coach_id=coach_id, athlete_id=athlete_id)
    client = make_e2e_demo_client()

    token = client.post(
        "/auth/demo-login",
        json={"email": "t3-07-coach@runsense.e2e", "password": "DemoPass!2026"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post("/me/settings/mfa/verify", json={"code": "424242"}, headers=headers).status_code == 200
    assert client.get(f"/teams/{team_id}/roster", headers=headers).status_code == 200

    sess_id = client.get("/me/settings/sessions", headers=headers).json()["items"][0]["id"]
    assert client.delete(f"/me/settings/sessions/{sess_id}", headers=headers).status_code == 204
    assert client.get(f"/teams/{team_id}/roster", headers=headers).status_code == 403


def test_t3_08_f3_x_f5_fit_and_wellness_inputs_feed_plan_ranker_and_trimp() -> None:
    """F3 x F5/F7 (M2 + M3 Contract): Parsed FIT (resting_hr + workout_rpe=0 HR_TRIMP) + wellness feeds MLPlanRanker."""
    parsed = parse_fit(
        build_synthetic_fit_bytes(
            duration_seconds=60, base_hr=148, resting_hr=52, device_max_hr=192, workout_rpe=0
        )
    )
    bundle = build_synthetic_garmin_gdpr_bundle(days=7)
    assert parsed["session"]["avg_hr"] is not None
    assert parsed["hr_profile"]["resting_hr"] == 52
    assert parsed["session"]["workout_rpe"] == 0
    assert len(bundle["uds"]) == 7

    trimp_rpe, _, metric = compute_hr_trimp_rpe(
        30.0,
        parsed["session"]["avg_hr"],
        parsed["hr_profile"]["max_hr"],
        parsed["hr_profile"]["resting_hr"],
    )
    assert metric == "HR_TRIMP"
    assert 1 <= trimp_rpe <= 10

    # PROJECT.md Interface Contract #1: optional wellness inputs on TrainingPlanContext
    ctx = TrainingPlanContext(
        triage_urgency=None,
        observation_days=21,
        acute_load=320.0,
        chronic_load=300.0,
        temperature_c=24.0,
        weather_state="LIVE",
        recent_avg_hr_bpm=float(parsed["session"]["avg_hr"]),
        avg_rpe_7d=float(trimp_rpe),
        resting_hr_delta=3.5,
        sleep_hours=7.2,
        load_ramp_pct=6.7,
    )
    candidates = generate_training_plan_candidates(ctx)
    res = MLPlanRanker().rank(ctx, candidates)
    assert res.abstained is False
    assert res.ranker_version == "ml-plan-ranker-xgboost-v1"
    assert res.ranked_candidates


@requires_db
@pytest.mark.e2e_db
def test_t3_10_f3_x_f5_garmin_fit_and_wellness_feed_training_plan_and_react_db(
    admin_engine, make_e2e_db_client
) -> None:
    """F3 x F5 x F7 DB: /garmin/fit/upload + /garmin/wellness/import feed /training-plan/today and ReAct tools."""
    import base64
    from app.db import actor_transaction

    athlete_id = seed_user(admin_engine, city="Taipei", sex="female")
    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )

    fit_bytes = build_synthetic_fit_bytes(
        duration_seconds=120, base_hr=152, max_hr=170, resting_hr=52, device_max_hr=192, workout_rpe=0
    )
    up = client.post(
        "/garmin/fit/upload",
        json={"fit_base64": base64.b64encode(fit_bytes).decode("ascii")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["source_metric"] == "HR_TRIMP"

    bundle = build_synthetic_garmin_gdpr_bundle(start_date=date(2026, 11, 17), days=7)
    imp = client.post(
        "/garmin/wellness/import",
        json={"uds": bundle["uds"], "sleep": bundle["sleep"]},
    )
    assert imp.status_code == 200 and imp.json()["imported_days"] == 7

    plan = client.get("/training-plan/today")
    assert plan.status_code == 200, plan.text
    assert plan.json()["candidates"]

    conn_gen = _get_connection_as_runtime_role()
    conn = next(conn_gen)
    try:
        with actor_transaction(conn, str(athlete_id)) as tx:
            outcome = run_unified_react_coach(
                question="看一下我的 Garmin 睡眠恢復與今天課表",
                athlete_id=athlete_id,
                conn=tx,
                local_date=_TODAY,
                context={"observation_days": 14, "acute_load": 280.0, "chronic_load": 260.0, "load_ratio": 1.08},
                llm_complete_fn=lambda msgs, ctx: ("已檢視您的恢復與負荷，今日可維持輕鬆有氧。", "MODEL"),
            )
            assert [s.action for s in outcome.trace][:2] == [
                "observe_athlete_status",
                "get_wellness_baseline",
            ]
            assert "Garmin 恢復指標" in outcome.trace[1].observation
    finally:
        conn_gen.close()


def test_t3_09_f6_x_f9_prompt_clinician_guidance_renders_valid_local_media_cards(
    make_no_db_client, no_external_apis
) -> None:
    athlete_id = uuid.uuid4()
    passage = EvidencePassage(
        evidence_id="ev-bone-01",
        title="Bone Stress Injury Running Guidelines",
        publisher="BJSM",
        source_url="https://example.org/ev-bone-01",
        revision_date="2025-01-01",
        license_or_provenance="reviewed",
        corpus_version="sports-medicine-v1",
        text="Stop weight-bearing impact running until evaluated.",
    )
    triage = assess_safety_triage(
        make_safety_triage_input(
            severity_band="MODERATE",
            body_part="shin",
            localized_bone_pain_worse_with_weight_bearing=True,
        )
    )
    guidance = compose_injury_guidance(triage, (passage,), configured_guidance_provider())
    assert guidance.urgency == TriageUrgency.PROMPT_CLINICIAN
    assert guidance.running_allowed is False

    client = make_no_db_client(actor_id=str(athlete_id))
    for fmt in ("png", "svg"):
        media_res = client.post(
            "/guidance/media",
            json={
                "topic": "Tibial Bone Pain Safety Guide",
                "body_part": "shin",
                "triage_urgency": guidance.urgency.value,
                "running_allowed": guidance.running_allowed,
                "guidance_summary": guidance.summary,
                "next_steps": list(guidance.next_steps)[:3],
                "citations": [c.title for c in guidance.citations],
                "media_format": fmt,
            },
        )
        assert media_res.status_code == 200, media_res.text
        raw = decode_media_response_bytes(media_res.json())
        if fmt == "png":
            assert_valid_png(raw)
        else:
            svg_text = raw.decode("utf-8")
            assert_valid_svg(raw)
            assert "RUNNING NOT ALLOWED" in svg_text
            assert "Bone Stress Injury Running Guidelines" in svg_text

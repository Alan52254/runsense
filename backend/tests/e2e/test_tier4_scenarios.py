"""Tier 4 E2E tests: 6 realistic multi-step end-to-end user journeys (T4-01..T4-06)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import text

from app import llm_client
from app.health_guidance_service import configured_guidance_provider
from app.injury_guidance import compose_injury_guidance
from app.plan_ranking import DeterministicPlanRanker, MLPlanRanker
from app.safety_triage import SafetyTriageInput, TriageUrgency, assess_safety_triage
from app.training_plan_candidates import TrainingPlanContext, generate_training_plan_candidates

from tests.e2e.conftest import (
    assert_valid_png,
    assert_valid_svg,
    decode_media_response_bytes,
    make_safety_triage_input,
    parse_sse_events,
    requires_db,
    seed_team_and_members,
    seed_user,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_tier4]

_FIXED_UTC = datetime(2026, 11, 23, 8, 0, 0, tzinfo=timezone.utc)


@requires_db
@pytest.mark.e2e_db
def test_t4_01_taipei_hot_weather_runner_daily_twin_and_soft_delete_recompute(
    admin_engine, make_e2e_demo_client
) -> None:
    """T4-01: Login -> profile (Taipei/female/HR) -> activities + weather -> plan + guidance -> soft delete -> recompute."""
    seed_user(
        admin_engine,
        email="taipei-runner@runsense.e2e",
        password="RunnerPass!2026",
        timezone_name="Asia/Taipei",
    )
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weather_cache (city, temperature_c, humidity_pct, provider_observed_at, fetched_at, "
                "sunrise_utc, sunset_utc, utc_offset_seconds) "
                "VALUES ('Taipei', 31.5, 78.0, now(), now(), "
                "'2026-11-22T22:15:00Z', '2026-11-23T09:05:00Z', 28800) "
                "ON CONFLICT (city) DO UPDATE SET temperature_c=31.5, humidity_pct=78.0, fetched_at=now()"
            )
        )

    client = make_e2e_demo_client(clock_utc=_FIXED_UTC)
    token = client.post(
        "/auth/demo-login",
        json={"email": "taipei-runner@runsense.e2e", "password": "RunnerPass!2026"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    prof = client.patch(
        "/profile",
        headers=headers,
        json={"city": "Taipei", "sex": "female", "max_hr_bpm": 192, "resting_hr_bpm": 50},
    )
    assert prof.status_code == 200

    # Log 8 runs across 14 days so observation history >= 7
    act_ids: list[str] = []
    for day_offset in range(0, 14, 2):
        ts = (_FIXED_UTC - timedelta(days=day_offset)).strftime("%Y-%m-%dT06:00:00Z")
        r = client.post(
            "/activities",
            headers=headers,
            json={
                "client_mutation_id": str(uuid.uuid4()),
                "duration_minutes": 40,
                "rpe": 5,
                "performed_at": ts,
                "distance_km": 7.0,
            },
        )
        assert r.status_code == 201
        act_ids.append(r.json()["id"])

    weather = client.get("/weather?segment_offsets_min=0&segment_offsets_min=30", headers=headers).json()
    assert weather["speed_loss_pct"] > 0.0
    assert len(weather["segment_estimates"]) == 2

    plan_before = client.get("/training-plan/today", headers=headers).json()
    assert plan_before["inputs"]["observation_days"] >= 7

    g1 = client.get("/guidance/today?llm_tone_enabled=false", headers=headers).json()
    g2 = client.get("/guidance/today?llm_tone_enabled=false", headers=headers).json()
    assert g1["computed_at"] == g2["computed_at"]

    # Soft delete most recent activity and verify zero ghost count
    assert client.delete(f"/activities/{act_ids[0]}", headers=headers).status_code == 204
    history = client.get("/activities", headers=headers).json()
    assert all(item["id"] != act_ids[0] for item in history["items"])
    report = client.get("/training-plan/model-report", headers=headers).json()
    assert report["athlete_history"]["completed_activities"] == len(act_ids) - 1


@requires_db
@pytest.mark.e2e_db
def test_t4_02_red_flag_bone_pain_safety_lock_multimedia_and_plan_lock(
    admin_engine, make_e2e_db_client, patch_chat_test_engine, scripted_groq_transport
) -> None:
    """T4-02: Athlete @AI bone-pain report -> confirm -> adversarial plan override -> local SVG -> plan locked."""
    def _groq_body_handler(body: dict[str, object]) -> dict[str, object]:
        return {
            "body_part": "脛骨",
            "pain_score": 8,
            "description": "左腳脛骨局部骨頭痛、踩地更痛",
            "red_flags": {"localized_bone_pain_worse_with_weight_bearing": True},
        }

    scripted_groq_transport(_groq_body_handler)
    coach_id = seed_user(admin_engine)
    athlete_id = seed_user(admin_engine)
    seed_team_and_members(admin_engine, coach_id=coach_id, athlete_id=athlete_id)

    client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=_FIXED_UTC,
    )
    rooms = client.get("/chat/rooms").json()["rooms"]
    direct_room = [r for r in rooms if r["kind"] == "direct"][0]

    sent = client.post(
        f"/chat/rooms/{direct_room['id']}/messages",
        json={"body": "@AI 我今天左腳脛骨局部骨頭痛、踩地更痛，疼痛 8 分"},
    )
    assert sent.status_code == 201
    msgs = client.get(f"/chat/rooms/{direct_room['id']}/messages").json()
    body_cards = [c for c in msgs["cards"] if c["kind"] == "body_report"]
    assert len(body_cards) == 1, f"Expected @AI to create 1 body_report card, got {msgs}"
    card = body_cards[0]
    if not card["payload"].get("severity_band"):
        edited = client.put(
            f"/chat/cards/{card['id']}",
            json={"body_part": "shin", "severity_band": "SEVERE"},
        )
        assert edited.status_code == 200, edited.text

    confirmed = client.post(f"/chat/cards/{card['id']}/confirm-report")
    assert confirmed.status_code == 200, confirmed.text

    reports = client.get("/injury-reports").json()["items"]
    assert len(reports) == 1
    assert reports[0]["severity_band"] == "SEVERE"

    guidance = client.post(
        "/injury-guidance",
        json={
            "injury_report_id": reports[0]["id"],
            "localized_bone_pain_worse_with_weight_bearing": True,
        },
    ).json()
    assert guidance["urgency"] in {"PROMPT_CLINICIAN", "EMERGENCY"}
    assert guidance["running_allowed"] is False

    media = client.post(
        "/guidance/media",
        json={
            "topic": "Bone Stress Safety Card",
            "body_part": "shin",
            "triage_urgency": guidance["urgency"],
            "running_allowed": True,  # Adversarial override attempt
            "guidance_summary": guidance["summary"],
            "next_steps": guidance["next_steps"][:3],
            "media_format": "svg",
        },
    ).json()
    svg_text = decode_media_response_bytes(media).decode("utf-8")
    assert "RUNNING NOT ALLOWED" in svg_text

    # Adversarial MILD + 90 min evaluate attempt must remain locked to REST_AND_SEEK_CARE
    plan_eval = client.post(
        "/training-plan/evaluate",
        json={"available_minutes": 90, "reported_severity_band": "MILD"},
    ).json()
    assert [c["workout_type"] for c in plan_eval["candidates"]] == ["REST_AND_SEEK_CARE"]
    assert plan_eval["candidates"][0]["running_allowed"] is False


@requires_db
@pytest.mark.e2e_db
def test_t4_03_team_privacy_consent_lifecycle_ai_guard_and_non_leak_departure(
    admin_engine, make_e2e_demo_client, patch_chat_test_engine, scripted_groq_transport
) -> None:
    """T4-03: Coach MFA -> athlete accept & grant -> team @AI privacy_guard vs direct @AI -> revoke -> leave -> 404."""
    def _groq_data_handler(body: dict[str, object]) -> dict[str, object]:
        msgs = body.get("messages") or []
        sys_txt = str((msgs[0] if msgs else {}).get("content") or "")
        if "允許的 intent" in sys_txt:
            return {"intent": "data"}
        return {"thought": "檢查選手訓練負荷", "action": "observe_athlete_status"}

    scripted_groq_transport(_groq_data_handler)
    coach_id = seed_user(admin_engine, email="t4-03-coach@runsense.e2e", password="DemoPass!2026")
    athlete_id = seed_user(admin_engine, email="t4-03-ath@runsense.e2e", password="DemoPass!2026")
    team_id = seed_team_and_members(
        admin_engine, coach_id=coach_id, athlete_id=athlete_id, athlete_status="INVITED"
    )
    client = make_e2e_demo_client(clock_utc=_FIXED_UTC)

    coach_tok = client.post(
        "/auth/demo-login",
        json={"email": "t4-03-coach@runsense.e2e", "password": "DemoPass!2026"},
    ).json()["access_token"]
    ath_tok = client.post(
        "/auth/demo-login",
        json={"email": "t4-03-ath@runsense.e2e", "password": "DemoPass!2026"},
    ).json()["access_token"]
    coach_h = {"Authorization": f"Bearer {coach_tok}"}
    ath_h = {"Authorization": f"Bearer {ath_tok}"}

    assert client.post("/me/settings/mfa/verify", json={"code": "424242"}, headers=coach_h).status_code == 200
    assert client.patch(f"/me/team-memberships/{team_id}", json={"action": "accept"}, headers=ath_h).status_code == 200
    for scope in ("activity_summary", "training_load"):
        assert client.patch(
            f"/me/consent-grants/{scope}",
            json={"team_id": str(team_id), "granted": True},
            headers=ath_h,
        ).status_code == 200

    assert client.get(f"/teams/{team_id}/roster", headers=coach_h).status_code == 200

    rooms = client.get("/chat/rooms", headers=coach_h).json()["rooms"]
    team_room = [r for r in rooms if r["kind"] == "team"][0]
    direct_room = [r for r in rooms if r["kind"] == "direct"][0]

    team_sent = client.post(f"/chat/rooms/{team_room['id']}/messages", json={"body": "@AI 查選手負荷"}, headers=coach_h)
    assert team_sent.status_code == 201
    team_msgs = client.get(f"/chat/rooms/{team_room['id']}/messages", headers=coach_h).json()["messages"]
    assert any("群組裡不公開" in m["body"] for m in team_msgs if m["sender_kind"] == "ai")

    dir_sent = client.post(f"/chat/rooms/{direct_room['id']}/messages", json={"body": "@AI 看選手訓練負荷"}, headers=coach_h)
    assert dir_sent.status_code == 201
    direct_msgs = client.get(f"/chat/rooms/{direct_room['id']}/messages", headers=coach_h).json()["messages"]
    assert any("狀態觀測" in m["body"] for m in direct_msgs if m["sender_kind"] == "ai")

    assert client.patch(
        f"/me/consent-grants/training_load",
        json={"team_id": str(team_id), "granted": False},
        headers=ath_h,
    ).status_code == 200

    assert client.patch(f"/me/team-memberships/{team_id}", json={"action": "leave"}, headers=ath_h).status_code == 200
    assert client.get(f"/teams/{team_id}/roster", headers=coach_h).json()["items"] == []
    assert client.get(f"/teams/{team_id}/athletes/{athlete_id}", headers=coach_h).status_code == 404


@requires_db
@pytest.mark.e2e_db
def test_t4_04_coach_athlete_proposal_share_schedule_draft_and_batch_revoke(
    admin_engine, make_e2e_db_client, scripted_coach_provider
) -> None:
    """T4-04: Athlete /guidance/chat/stream -> share -> coach schedule-suggestion/draft -> confirm -> batch revoke."""
    from zoneinfo import ZoneInfo

    coach_id = seed_user(admin_engine)
    athlete_id = seed_user(admin_engine)
    seed_team_and_members(
        admin_engine, coach_id=coach_id, athlete_id=athlete_id, consent_scopes=("training_load",)
    )
    scripted_coach_provider(
        answer_text="今天可以先進行 30 分鐘輕鬆跑。",
        json_override={"available_minutes": 30},
    )

    now_utc = datetime.now(timezone.utc)
    taipei_tz = ZoneInfo("Asia/Taipei")
    today_taipei = now_utc.astimezone(taipei_tz).date()

    ath_client = make_e2e_db_client(
        actor_id=str(athlete_id),
        timezones={str(athlete_id): "Asia/Taipei"},
        clock_utc=now_utc,
    )
    coach_client = make_e2e_db_client(actor_id=str(coach_id))

    # Seed 14 steady runs across 28 days so chronic load >= acute load and schedule-draft emits 7 run days
    for day_offset in range(1, 29, 2):
        local_dt = datetime.combine(
            today_taipei - timedelta(days=day_offset),
            datetime.min.time(),
            tzinfo=taipei_tz,
        ).replace(hour=6)
        r = ath_client.post(
            "/activities",
            json={
                "client_mutation_id": str(uuid.uuid4()),
                "duration_minutes": 40,
                "rpe": 5,
                "performed_at": local_dt.astimezone(timezone.utc).isoformat(),
                "distance_km": 7.0,
            },
        )
        assert r.status_code == 201, r.text

    stream = ath_client.post(
        "/guidance/chat/stream",
        json={"messages": [{"role": "user", "content": "今天只有 30 分鐘"}]},
    )
    proposal = [e["proposal"] for e in parse_sse_events(stream.text) if "proposal" in e][0]
    assert ath_client.post(f"/guidance/proposals/{proposal['id']}/share").status_code == 200

    rooms = coach_client.get("/chat/rooms").json()["rooms"]
    direct_room = [r for r in rooms if r["kind"] == "direct"][0]

    draft = coach_client.post(f"/chat/rooms/{direct_room['id']}/schedule-draft", json={})
    assert draft.status_code == 201, draft.text
    assert len(draft.json()["payload"]["plan"]["days"]) >= 1
    card_id = draft.json()["id"]
    confirmed = coach_client.post(f"/chat/cards/{card_id}/confirm-plan", json={})
    assert confirmed.status_code == 200, confirmed.text
    batch_id = confirmed.json().get("batch_id")
    assert batch_id, f"confirm-plan must return non-empty batch_id: {confirmed.json()}"
    revoked = coach_client.post(f"/chat/batches/{batch_id}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["removed"] >= 1


@requires_db
@pytest.mark.e2e_db
def test_t4_05_multi_tenant_cross_team_forced_rls_and_revoked_session_isolation(
    admin_engine, make_e2e_demo_client
) -> None:
    """T4-05: Team A vs Team B + outsiders under runsense_runtime forced RLS and revoked JWT isolation."""
    coach_a = seed_user(admin_engine, email="t4-05-ca@runsense.e2e", password="DemoPass!2026")
    ath_a = seed_user(admin_engine, email="t4-05-aa@runsense.e2e", password="DemoPass!2026")
    coach_b = seed_user(admin_engine, email="t4-05-cb@runsense.e2e", password="DemoPass!2026")
    ath_b = seed_user(admin_engine, email="t4-05-ab@runsense.e2e", password="DemoPass!2026")

    team_a = seed_team_and_members(
        admin_engine, coach_id=coach_a, athlete_id=ath_a, team_name="E2E Track Club A"
    )
    team_b = seed_team_and_members(
        admin_engine, coach_id=coach_b, athlete_id=ath_b, team_name="E2E Track Club B"
    )

    client = make_e2e_demo_client(clock_utc=_FIXED_UTC)
    tok_ca = client.post(
        "/auth/demo-login", json={"email": "t4-05-ca@runsense.e2e", "password": "DemoPass!2026"}
    ).json()["access_token"]
    tok_aa = client.post(
        "/auth/demo-login", json={"email": "t4-05-aa@runsense.e2e", "password": "DemoPass!2026"}
    ).json()["access_token"]
    tok_ab = client.post(
        "/auth/demo-login", json={"email": "t4-05-ab@runsense.e2e", "password": "DemoPass!2026"}
    ).json()["access_token"]

    ca_h = {"Authorization": f"Bearer {tok_ca}"}
    aa_h = {"Authorization": f"Bearer {tok_aa}"}
    ab_h = {"Authorization": f"Bearer {tok_ab}"}

    client.post("/me/settings/mfa/verify", json={"code": "424242"}, headers=ca_h)
    assert client.get(f"/teams/{team_a}/roster", headers=ca_h).status_code == 200
    assert client.get(f"/teams/{team_b}/roster", headers=ca_h).status_code == 403
    assert client.get(f"/teams/{team_b}/athletes/{ath_b}", headers=ca_h).status_code == 403

    # Same client_mutation_id isolated per actor
    shared_mut = str(uuid.uuid4())
    p = {
        "client_mutation_id": shared_mut,
        "duration_minutes": 30,
        "rpe": 5,
        "performed_at": "2026-11-23T06:00:00Z",
    }
    r_a = client.post("/activities", json=p, headers=aa_h)
    r_b = client.post("/activities", json=p, headers=ab_h)
    assert r_a.status_code == 201 and r_b.status_code == 201
    assert r_a.json()["id"] != r_b.json()["id"]

    # Revoke Coach A session -> immediately rejected across routes
    sess_a = client.get("/me/settings/sessions", headers=ca_h).json()["items"][0]["id"]
    assert client.delete(f"/me/settings/sessions/{sess_a}", headers=ca_h).status_code == 204
    assert client.get(f"/teams/{team_a}/roster", headers=ca_h).status_code == 403


def test_t4_06_zero_external_api_degraded_infrastructure_resilience(
    make_no_db_client, no_external_apis, monkeypatch
) -> None:
    """T4-06: All external LLM/Weather/Media keys & ffmpeg unavailable -> every fallback completes cleanly without 500."""
    monkeypatch.setenv("RUNSENCE_FFMPEG_BIN", "missing_ffmpeg_e2e_bin")
    actor_id = uuid.uuid4()
    client = make_no_db_client(actor_id=str(actor_id))

    # 1. /healthz/providers unauthenticated check
    hz = client.get("/healthz/providers")
    assert hz.status_code == 200

    # 2. /guidance/media PNG, SVG, and MP4->SVG fallback all succeed cleanly
    for fmt in ("png", "svg", "mp4"):
        res = client.post(
            "/guidance/media",
            json={
                "topic": "Offline Resilience Health Guide",
                "triage_urgency": "SELF_CARE_NEXT_STEP",
                "guidance_summary": "Fallback rendering works completely offline.",
                "next_steps": ["Rest 48h", "Monitor symptoms"],
                "media_format": fmt,
            },
        )
        assert res.status_code == 200, res.text
        raw = decode_media_response_bytes(res.json())
        if fmt == "png":
            assert_valid_png(raw)
        else:
            assert_valid_svg(raw)

    # 3. Injury guidance degrades to static-fallback while preserving triage
    triage = assess_safety_triage(make_safety_triage_input(severity_band="MODERATE", body_part="knee"))
    g_out = compose_injury_guidance(triage, (), configured_guidance_provider())
    assert g_out.used_fallback is True
    assert g_out.provider_name == "static-fallback"
    assert g_out.urgency == TriageUrgency.SELF_CARE_NEXT_STEP
    assert g_out.running_allowed is False

    # 4. llm_client.coach_turn degrades safely to NOT_CONFIGURED / UNAVAILABLE
    turn = llm_client.coach_turn([{"role": "user", "content": "怎麼跑？"}], {"observation_days": 0})
    assert turn.answer.source in {"NOT_CONFIGURED", "UNAVAILABLE"}

    # 5. Plan ranker cold-start / unavailable weather abstains cleanly to deterministic ladder
    ctx = TrainingPlanContext(
        triage_urgency=None,
        observation_days=2,
        acute_load=None,
        chronic_load=None,
        temperature_c=None,
        weather_state="UNAVAILABLE",
    )
    candidates = generate_training_plan_candidates(ctx)
    det_res = DeterministicPlanRanker().rank(ctx, candidates)
    ml_res = MLPlanRanker().rank(ctx, candidates)
    assert det_res.abstained is True and ml_res.abstained is True
    assert det_res.ranked_candidates and ml_res.ranked_candidates

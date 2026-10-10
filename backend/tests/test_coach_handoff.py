"""Who decides what between the AI 健康教練, the Athlete and the coach
(app/coach_handoff.py, ADR 0003), and the persona files that only shape
wording (app/personas)."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app import chat_service, coach_handoff, personas
from app.chat_plan import day_blocking_problems
from conftest import requires_db

_EASY = {"candidate_id": "easy-40", "workout_type": "EASY_RUN", "duration_minutes": 40,
         "distance_km": 6.5, "running_allowed": True}
_REST = {"candidate_id": "rest-day", "workout_type": "REST_DAY", "duration_minutes": 0,
         "distance_km": 0, "running_allowed": False}


# ---------------------------------------------------------------- personas


def test_each_surface_has_its_own_soul():
    coach, assistant = personas.soul("health_coach"), personas.soul("team_assistant")
    assert coach and assistant and coach != assistant
    assert "健康教練" in coach
    assert "RunSense助手" in assistant


def test_extraction_skills_carry_no_soul():
    """Rewriting a SOUL.md cannot change what gets extracted."""
    for persona, name in (("health_coach", "extract_facts"), ("team_assistant", "router"),
                          ("team_assistant", "body_report"), ("team_assistant", "schedule")):
        prompt = personas.system_prompt(persona, name, with_soul=False)
        assert personas.soul(persona) not in prompt
        assert prompt == personas.skill(persona, name)


def test_a_missing_soul_leaves_the_job_intact(tmp_path, monkeypatch):
    (tmp_path / "health_coach" / "skills").mkdir(parents=True)
    (tmp_path / "health_coach" / "skills" / "consult.md").write_text("只做這件事", encoding="utf-8")
    monkeypatch.setattr(personas, "_ROOT", tmp_path)
    personas.soul.cache_clear()
    personas.skill.cache_clear()
    try:
        assert personas.system_prompt("health_coach", "consult") == "只做這件事"
    finally:
        personas.soul.cache_clear()
        personas.skill.cache_clear()


# ---------------------------------------------------------------- hard routing


def _never_called():
    raise AssertionError("the model must not be consulted")


def test_athlete_red_flag_words_reach_a_body_report_without_the_model():
    assert chat_service.route("跑完胸悶，有點呼吸困難", "athlete", _never_called) == "body_report"


@pytest.mark.parametrize(("role", "model_says", "routed"), [
    ("athlete", "schedule", chat_service.REDIRECT_TO_COACH),  # athletes never schedule
    ("athlete", "body_report", "body_report"),
    ("athlete", "question", "question"),
    ("coach", "schedule", "schedule"),
    ("coach", "body_report", "question"),  # a coach files no body report
    ("head_coach", "schedule", "schedule"),
])
def test_role_fixes_what_the_model_may_choose(role, model_says, routed):
    assert chat_service.route("@AI 明天", role, lambda: model_says) == routed


def test_a_coach_quoting_symptoms_is_not_turned_into_a_body_report():
    assert chat_service.route("選手說胸悶", "coach", lambda: "question") == "question"


# ---------------------------------------------------------------- suggestion -> plan card


def _suggestion(candidate=_EASY, day="2026-10-12"):
    return {"kind": coach_handoff.SUGGESTION_KIND, "proposal_id": "p1", "date": day, "label": "小腿緊",
            "candidate": candidate, "facts": {}, "coach_assigned": []}


def test_a_suggestion_becomes_one_confirmable_day_with_the_engine_numbers():
    athlete = {"id": str(uuid.uuid4()), "name": "東京選手", "sex": "female"}
    payload = coach_handoff.plan_payload_from_suggestion(_suggestion(), athlete, "原文", date(2026, 10, 10))

    (day,) = payload["plan"]["days"]
    assert day["date"] == "2026-10-12" and day["problems"] == [] and not day_blocking_problems(day)
    assert payload["athletes"] == [{**athlete, "selected": True}]
    record = chat_service.assignment_record(day["items"][0], athlete["sex"])
    assert record["intensity_label"] == "輕鬆跑" and record["tracked"] is True
    assert record["duration_minutes"] == 40
    assert record["structure"] == [{"kind": "jog", "label": "輕鬆跑 40 分鐘 · 6.5 km",
                                    "durationSeconds": 2400, "distanceMeters": 6500}]


def test_a_rest_suggestion_has_nothing_to_schedule():
    with pytest.raises(coach_handoff.SuggestionNotSchedulable):
        coach_handoff.plan_payload_from_suggestion(
            _suggestion(_REST), {"id": "a", "name": "x", "sex": None}, "", date(2026, 10, 10))


# ---------------------------------------------------------------- the whole handoff, against the database


def _setup(admin_engine):
    team_id, coach_id, athlete_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        for uid, name in ((coach_id, "臺北教練"), (athlete_id, "東京選手")):
            conn.execute(text("INSERT INTO users (id, email, password_hash, display_name) "
                              "VALUES (:id, :e, 'x', :n)"), {"id": uid, "e": f"{uid}@example.test", "n": name})
        conn.execute(text("INSERT INTO teams (id, name) VALUES (:id, 't')"), {"id": team_id})
        for uid, role in ((coach_id, "coach"), (athlete_id, "athlete")):
            conn.execute(text("INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) "
                              "VALUES (:t, :u, :r, 'ACTIVE', now())"), {"t": team_id, "u": uid, "r": role})
    return team_id, coach_id, athlete_id


def _proposal(admin_engine, athlete_id, day, candidate=_EASY):
    with admin_engine.begin() as conn:
        return conn.execute(text(
            """INSERT INTO coach_proposals (athlete_id, local_training_date, label, scenario_override,
                 changed_facts, plan_summary, ranker_version, abstained)
               VALUES (:a, :d, '小腿緊', '{}'::jsonb, ARRAY['reported_body_part'], CAST(:s AS jsonb), 'v1', false)
               RETURNING id"""),
            {"a": athlete_id, "d": day, "s": json.dumps({"candidates": [candidate]})}).scalar_one()


@requires_db
def test_athlete_shares_coach_schedules_and_the_day_becomes_the_coachs(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup(admin_engine)
    day = date.today() + timedelta(days=2)
    proposal_id = _proposal(admin_engine, athlete_id, day)
    # make_client swaps the app-wide actor, so take a fresh client per call
    def athlete():
        return make_client(actor_id=str(athlete_id))

    def coach():
        return make_client(actor_id=str(coach_id))

    # the athlete sends it; sending twice posts it once
    shared = athlete().post(f"/guidance/proposals/{proposal_id}/share")
    assert shared.status_code == 200, shared.text
    (room_id,) = shared.json()["room_ids"]
    assert athlete().post(f"/guidance/proposals/{proposal_id}/share").json()["room_ids"] == [room_id]

    messages = coach().get(f"/chat/rooms/{room_id}/messages").json()["messages"]
    (suggestion,) = [m for m in messages if m["payload"].get("kind") == coach_handoff.SUGGESTION_KIND]
    assert suggestion["payload"]["candidate"]["workout_type"] == "EASY_RUN"

    # only the coach can turn it into a plan, and nothing is written until confirmed
    denied = athlete().post(f"/chat/messages/{suggestion['id']}/schedule-suggestion")
    assert denied.status_code == 403
    card = coach().post(f"/chat/messages/{suggestion['id']}/schedule-suggestion")
    assert card.status_code == 201, card.text
    assert card.json()["preview"]["rows"][0]["entries"][0]["status"] == "new"
    with admin_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM assigned_workouts")).scalar_one() == 0

    confirmed = coach().post(f"/chat/cards/{card.json()['id']}/confirm-plan")
    assert confirmed.status_code == 200, confirmed.text
    with admin_engine.begin() as conn:
        row = conn.execute(text("SELECT local_date, intensity_label, tracked FROM assigned_workouts "
                                "WHERE athlete_id=:a"), {"a": athlete_id}).one()
    assert (row.local_date, row.intensity_label, row.tracked) == (day, "輕鬆跑", True)

    # that day is now the coach's: the athlete can no longer apply a suggestion to it
    accepted = athlete().post(f"/guidance/proposals/{proposal_id}/accept")
    assert accepted.json() == {"applied": False, "reason": "COACH_SCHEDULED"}


@requires_db
def test_a_retracted_suggestion_cannot_be_scheduled(make_client, admin_engine):
    team_id, coach_id, athlete_id = _setup(admin_engine)
    proposal_id = _proposal(admin_engine, athlete_id, date.today() + timedelta(days=3))

    def athlete():
        return make_client(actor_id=str(athlete_id))

    def coach():
        return make_client(actor_id=str(coach_id))

    (room_id,) = athlete().post(f"/guidance/proposals/{proposal_id}/share").json()["room_ids"]
    (suggestion,) = [m for m in coach().get(f"/chat/rooms/{room_id}/messages").json()["messages"]
                     if m["payload"].get("kind") == coach_handoff.SUGGESTION_KIND]
    card_id = coach().post(f"/chat/messages/{suggestion['id']}/schedule-suggestion").json()["id"]
    assert athlete().post(f"/chat/messages/{suggestion['id']}/retract").status_code == 204

    refused = coach().post(f"/chat/cards/{card_id}/confirm-plan")
    assert refused.status_code == 409
    with admin_engine.begin() as conn:
        assert conn.execute(text("SELECT status FROM chat_cards WHERE id=:c"), {"c": card_id}).scalar_one() \
            == "cancelled"
        assert conn.execute(text("SELECT count(*) FROM assigned_workouts")).scalar_one() == 0


@requires_db
def test_someone_elses_proposal_cannot_be_shared(make_client, admin_engine):
    _, _, athlete_id = _setup(admin_engine)
    proposal_id = _proposal(admin_engine, athlete_id, date.today())
    stranger = make_client(actor_id=str(uuid.uuid4()))
    assert stranger.post(f"/guidance/proposals/{proposal_id}/share").status_code == 404


@requires_db
def test_rooms_are_created_on_first_use_under_row_level_security(make_client, admin_engine):
    """INSERT ... ON CONFLICT failed the rooms' read policy for the runtime
    role, so the very first GET /chat/rooms was a 500 (chat_service.ensure_room)."""
    _, coach_id, athlete_id = _setup(admin_engine)
    first = make_client(actor_id=str(athlete_id)).get("/chat/rooms")
    assert first.status_code == 200, first.text
    assert sorted(r["kind"] for r in first.json()["rooms"]) == ["direct", "team"]
    again = make_client(actor_id=str(coach_id)).get("/chat/rooms")
    assert sorted(r["kind"] for r in again.json()["rooms"]) == ["direct", "team"]


def test_the_scheduled_session_names_the_athletes_own_pace():
    paced = {**_EASY, "pace_range_s_per_km": [360, 380]}
    payload = coach_handoff.plan_payload_from_suggestion(
        _suggestion(paced), {"id": "a", "name": "東京選手", "sex": None}, "原文", date(2026, 10, 10))

    record = chat_service.assignment_record(payload["plan"]["days"][0]["items"][0], None)
    assert record["title"] == "輕鬆跑 40 分鐘 · 6.5 km · 配速 6:00–6:20/km"


# ---------------------------------------------------------------- the coach's answer reaches the athlete


def _shared_suggestion(make_client, admin_engine, *, days_ahead: int = 2):
    team_id, coach_id, athlete_id = _setup(admin_engine)
    proposal_id = _proposal(admin_engine, athlete_id, date.today() + timedelta(days=days_ahead))
    (room_id,) = make_client(actor_id=str(athlete_id)).post(
        f"/guidance/proposals/{proposal_id}/share").json()["room_ids"]
    (suggestion,) = [m for m in make_client(actor_id=str(coach_id)).get(f"/chat/rooms/{room_id}/messages")
                     .json()["messages"] if m["payload"].get("kind") == coach_handoff.SUGGESTION_KIND]
    return coach_id, athlete_id, room_id, suggestion["id"]


def _payload(admin_engine, message_id) -> dict:
    with admin_engine.begin() as conn:
        return conn.execute(text("SELECT payload FROM chat_messages WHERE id=:m"), {"m": message_id}).scalar_one()


@requires_db
def test_scheduling_a_suggestion_marks_it_adopted(make_client, admin_engine):
    coach_id, _, _, message_id = _shared_suggestion(make_client, admin_engine)
    card = make_client(actor_id=str(coach_id)).post(f"/chat/messages/{message_id}/schedule-suggestion").json()
    assert make_client(actor_id=str(coach_id)).post(f"/chat/cards/{card['id']}/confirm-plan").status_code == 200

    payload = _payload(admin_engine, message_id)
    assert payload["decision"] == "adopted"
    assert payload["batch_id"]


@requires_db
def test_a_suggestion_the_coach_edited_before_scheduling_is_adopted_with_changes(make_client, admin_engine):
    coach_id, _, _, message_id = _shared_suggestion(make_client, admin_engine)
    card = make_client(actor_id=str(coach_id)).post(f"/chat/messages/{message_id}/schedule-suggestion").json()
    day = card["payload"]["plan"]["days"][0]
    edited = make_client(actor_id=str(coach_id)).put(f"/chat/cards/{card['id']}", json={"days": [
        {"key": day["key"], "date": day["date"], "items": [
            {"type": "run", "kind": "easy", "title": "輕鬆跑 30 分鐘",
             "variants": {"all": [{"reps": 1, "duration_s": 1800}]}}]}]})
    assert edited.status_code == 200, edited.text
    assert make_client(actor_id=str(coach_id)).post(f"/chat/cards/{card['id']}/confirm-plan").status_code == 200

    assert _payload(admin_engine, message_id)["decision"] == "adopted_modified"


@requires_db
def test_the_coach_can_decline_a_suggestion_with_a_reason_and_the_athlete_cannot(make_client, admin_engine):
    coach_id, athlete_id, room_id, message_id = _shared_suggestion(make_client, admin_engine)
    pending = make_client(actor_id=str(coach_id)).post(f"/chat/messages/{message_id}/schedule-suggestion").json()

    assert make_client(actor_id=str(athlete_id)).post(
        f"/chat/messages/{message_id}/decline-suggestion", json={"reason": "我要"}).status_code == 403
    declined = make_client(actor_id=str(coach_id)).post(
        f"/chat/messages/{message_id}/decline-suggestion", json={"reason": "週六有測驗，這週先照原課表"})
    assert declined.status_code == 200, declined.text

    payload = _payload(admin_engine, message_id)
    assert (payload["decision"], payload["reason"]) == ("declined", "週六有測驗，這週先照原課表")
    with admin_engine.begin() as conn:
        assert conn.execute(text("SELECT status FROM chat_cards WHERE id=:c"),
                            {"c": pending["id"]}).scalar_one() == "cancelled"
    bodies = [m["body"] for m in make_client(actor_id=str(athlete_id)).get(
        f"/chat/rooms/{room_id}/messages").json()["messages"] if m["sender_kind"] == "system"]
    assert any("週六有測驗" in b for b in bodies)


# ---------------------------------------------------------------- the plan card shows what the plan does to the load


def _daily_runs(admin_engine, athlete_id, days: int = 28) -> None:
    """30 min at RPE 3 (load 90) on each of the last `days` days, not today."""
    from datetime import datetime, timezone

    from app.training_load_store import recompute_training_load

    with admin_engine.begin() as conn:
        for i in range(1, days + 1):
            day = date.today() - timedelta(days=i)
            conn.execute(text(
                """INSERT INTO completed_activities (athlete_id, client_mutation_id, request_fingerprint,
                     duration_minutes, rpe, performed_at, timezone_snapshot, local_training_date, session_load)
                   VALUES (:a, :c, 'f', 30, 3, :at, 'UTC', :d, 90)"""),
                {"a": athlete_id, "c": uuid.uuid4(), "d": day,
                 "at": datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc)})
        # materialize the daily load, as creating an activity does
        recompute_training_load(conn, athlete_id, date.today() - timedelta(days=days))


def _grant(admin_engine, team_id, athlete_id, scope="training_load") -> None:
    with admin_engine.begin() as conn:
        conn.execute(text("INSERT INTO consent_grants (team_id, athlete_id, scope, granted, changed_at) "
                          "VALUES (:t, :a, :s, true, now())"), {"t": team_id, "a": athlete_id, "s": scope})


def _plan_card_for_tomorrows_easy_run(make_client, admin_engine, *, consent: bool):
    team_id, coach_id, athlete_id = _setup(admin_engine)
    _daily_runs(admin_engine, athlete_id)
    if consent:
        _grant(admin_engine, team_id, athlete_id)
    proposal_id = _proposal(admin_engine, athlete_id, date.today() + timedelta(days=1))  # easy run, 40 min
    (room_id,) = make_client(actor_id=str(athlete_id)).post(
        f"/guidance/proposals/{proposal_id}/share").json()["room_ids"]
    (suggestion,) = [m for m in make_client(actor_id=str(coach_id)).get(f"/chat/rooms/{room_id}/messages")
                     .json()["messages"] if m["payload"].get("kind") == coach_handoff.SUGGESTION_KIND]
    card = make_client(actor_id=str(coach_id)).post(f"/chat/messages/{suggestion['id']}/schedule-suggestion").json()
    return card["preview"]["rows"][0]["entries"][0]


@requires_db
def test_the_plan_card_shows_the_load_ratio_before_and_after_scheduling(make_client, admin_engine):
    entry = _plan_card_for_tomorrows_easy_run(make_client, admin_engine, consent=True)

    # today: 6 x 90 / (27 x 90 / 4) = 0.89; tomorrow with 40 min easy (RPE 3 -> 120):
    # (5 x 90 + 120) / ((26 x 90 + 120) / 4) = 0.93
    assert entry["projected_load"] == {
        "before": 0.89, "after": 0.93, "on": (date.today() + timedelta(days=1)).isoformat(),
        "basis": "planned_rpe_by_session_type"}


@requires_db
def test_without_the_athletes_consent_the_coach_sees_no_load(make_client, admin_engine):
    entry = _plan_card_for_tomorrows_easy_run(make_client, admin_engine, consent=False)

    assert entry["projected_load"] is None
    assert entry["load_consent"] is False

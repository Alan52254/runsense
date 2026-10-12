"""DB-dependent tests for GET /teams/{team}/athletes/{athlete}/training-day:
the coach's view of what an athlete actually ran on an assigned day, and the
activity_telemetry_coach_read policy (migration 0030) it relies on. Requires
TEST_DATABASE_URL pointing at a separate Postgres database with migrations
applied; requests run as runsense_runtime so RLS is exercised.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import text

from conftest import requires_db
from tests.test_teams_roster import _insert_consent, _insert_membership, _insert_team, _insert_user
from tests.test_workout_segmentation import EASY, intervals, make_tele

from app.workout_segmentation import detect_workout

DAY = date(2026, 10, 8)


def _insert_run(admin_engine, *, athlete_id: uuid.UUID, hour: int, minute: int, minutes: float, km: float,
                tele: dict | None = None) -> uuid.UUID:
    """A Completed Activity on DAY, with its recording and import-time
    detection when `tele` is given."""
    activity_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO completed_activities (id, athlete_id, client_mutation_id, request_fingerprint, "
                " duration_minutes, rpe, performed_at, timezone_snapshot, local_training_date, session_load, "
                " distance_km) "
                "VALUES (:id, :a, :cmid, :fp, :m, 5, :at, 'UTC', :d, :load, :km)"
            ),
            {"id": activity_id, "a": athlete_id, "cmid": str(uuid.uuid4()), "fp": f"fp-{uuid.uuid4()}",
             "m": minutes, "at": datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=timezone.utc),
             "d": DAY, "load": minutes * 5, "km": km},
        )
        if tele is not None:
            detection = detect_workout(tele, EASY)
            conn.execute(
                text(
                    "INSERT INTO activity_telemetry (activity_id, athlete_id, sport, sub_sport, laps, timer_events, "
                    " workout_steps, samples, auto_detection, auto_summary) "
                    "VALUES (:id, :a, 'running', :sub, CAST(:laps AS jsonb), CAST(:ev AS jsonb), '[]'::jsonb, "
                    " CAST(:samples AS jsonb), CAST(:det AS jsonb), CAST(:summ AS jsonb))"
                ),
                {"id": activity_id, "a": athlete_id, "sub": tele["sub_sport"], "laps": json.dumps(tele["laps"]),
                 "ev": json.dumps(tele["timer_events"]), "samples": json.dumps(tele["samples"]),
                 "det": json.dumps(detection),
                 "summ": json.dumps({"kind": detection["kind"], "signature": detection["signature"]})},
            )
    return activity_id


def _team_with_athlete(admin_engine, tag: str, *, granted: bool = True):
    team_id = _insert_team(admin_engine, name=f"Training Day {tag}")
    coach_id = _insert_user(admin_engine, email=f"coach-day-{tag}@runsense.demo")
    athlete_id = _insert_user(admin_engine, email=f"athlete-day-{tag}@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")
    if granted:
        _insert_consent(admin_engine, team_id=team_id, athlete_id=athlete_id, scope="activity_summary", granted=True)
    return team_id, coach_id, athlete_id


def _warmup_session_cooldown(admin_engine, athlete_id: uuid.UUID):
    """A separately recorded warm-up, the interval session, and a cool-down
    -- in that order, so "the day's first or last activity" is never the
    session."""
    warm = _insert_run(admin_engine, athlete_id=athlete_id, hour=10, minute=0, minutes=6, km=1.3,
                       tele=make_tele([("steady", 360, EASY)], sub_sport="generic", manual_laps=False))
    session = _insert_run(admin_engine, athlete_id=athlete_id, hour=10, minute=40, minutes=40, km=6.0,
                          tele=make_tele(intervals(4, 1000, 4.5, 120, 0.0)))
    cool = _insert_run(admin_engine, athlete_id=athlete_id, hour=11, minute=30, minutes=18, km=3.2,
                       tele=make_tele([("steady", 1080, EASY)], sub_sport="generic", manual_laps=False))
    return warm, session, cool


def _get_day(make_client, team_id, coach_id, athlete_id):
    client = make_client(actor_id=str(coach_id), timezones={str(coach_id): "UTC"})
    return client.get(f"/teams/{team_id}/athletes/{athlete_id}/training-day", params={"local_date": str(DAY)})


@requires_db
def test_the_main_session_is_the_workout_not_the_days_first_or_last_run(make_client, admin_engine):
    team_id, coach_id, athlete_id = _team_with_athlete(admin_engine, "a")
    warm, session, cool = _warmup_session_cooldown(admin_engine, athlete_id)

    response = _get_day(make_client, team_id, coach_id, athlete_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["main_activity_id"] == str(session)
    assert [(i["id"], i["day_role"]) for i in body["items"]] == [
        (str(warm), "warmup"), (str(session), "main"), (str(cool), "cooldown")]
    # every watch lap of the session: warm-up, 4 reps, 3 recoveries, cool-down
    laps = body["laps"]
    assert laps["roles_from"] == "detection" and len(laps["laps"]) == 9
    assert [lap["role"] for lap in laps["laps"]].count("work") == 4
    assert all(lap["pace_s_per_km"] for lap in laps["laps"] if lap["role"] == "work")


@requires_db
def test_an_unanalysed_session_gets_a_read_only_reading_from_the_recording(make_client, admin_engine):
    team_id, coach_id, athlete_id = _team_with_athlete(admin_engine, "b")
    _warm, session, _cool = _warmup_session_cooldown(admin_engine, athlete_id)

    analysis = _get_day(make_client, team_id, coach_id, athlete_id).json()["analysis"]
    # reading the recording proves the coach can SELECT activity_telemetry
    assert analysis["source"] == "auto" and analysis["activity_id"] == str(session)
    assert analysis["signature_label"] == "4 × 1000m"
    assert len([s for s in analysis["segment_stats"] if s["role"] == "work"]) == 4
    assert analysis["findings"] and analysis["narrative_source"] == "offline"
    # computed on request, never stored
    with admin_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM workout_analyses")).scalar() == 0


@requires_db
def test_the_athletes_own_saved_analysis_is_shown_when_there_is_one(make_client, admin_engine):
    team_id, coach_id, athlete_id = _team_with_athlete(admin_engine, "c")
    _warm, session, _cool = _warmup_session_cooldown(admin_engine, athlete_id)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workout_analyses (activity_id, athlete_id, session_type, segments, signature, metrics, "
                " narrative, narrative_source) VALUES (:id, :a, 'intervals', '[]'::jsonb, '4x1000m', "
                " CAST(:m AS jsonb), '選手確認過的講評', 'llm')"
            ),
            {"id": session, "a": athlete_id,
             "m": json.dumps({"segment_stats": [], "summary": {}, "findings": [], "data_notes": []})},
        )

    analysis = _get_day(make_client, team_id, coach_id, athlete_id).json()["analysis"]
    assert analysis["source"] == "athlete"
    assert analysis["narrative"] == "選手確認過的講評"
    day = _get_day(make_client, team_id, coach_id, athlete_id).json()
    assert day["laps"]["roles_from"] == "analysis"


@requires_db
def test_nothing_is_shown_without_the_activity_summary_scope(make_client, admin_engine):
    team_id, coach_id, athlete_id = _team_with_athlete(admin_engine, "d", granted=False)
    _warmup_session_cooldown(admin_engine, athlete_id)

    response = _get_day(make_client, team_id, coach_id, athlete_id)
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "main_activity_id": None, "analysis": None, "laps": None,
                               "local_date": str(DAY)}


@requires_db
def test_an_athlete_cannot_read_a_team_mates_training_day(make_client, admin_engine):
    team_id, _coach_id, athlete_id = _team_with_athlete(admin_engine, "e")
    team_mate = _insert_user(admin_engine, email="team-mate-day-e@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=team_mate, role="athlete", status="ACTIVE")
    _warmup_session_cooldown(admin_engine, athlete_id)

    response = _get_day(make_client, team_id, team_mate, athlete_id)
    assert response.status_code == 403
    assert response.json() == {"error": "NOT_AUTHORIZED"}


def _as_runtime(admin_engine, actor_id: uuid.UUID, sql: str, params: dict):
    """Run one statement as runsense_runtime with `actor_id` as the actor --
    exactly how a request reaches the database."""
    with admin_engine.connect() as conn:
        conn.execute(text("SET ROLE runsense_runtime"))
        conn.commit()  # SET ROLE outlives the transaction; begin a fresh one below
        with conn.begin():
            conn.execute(text("SELECT set_config('app.actor_user_id', :a, true)"), {"a": str(actor_id)})
            result = conn.execute(text(sql), params)
            out = result.rowcount if result.returns_rows is False else result.all()
        conn.execute(text("RESET ROLE"))
        conn.commit()  # an uncommitted RESET ROLE is rolled back, and the pooled connection keeps the role
    return out


@requires_db
def test_the_coach_read_policy_on_telemetry_follows_the_consent_and_never_writes(admin_engine):
    team_id, coach_id, athlete_id = _team_with_athlete(admin_engine, "f")
    _warm, session, _cool = _warmup_session_cooldown(admin_engine, athlete_id)
    read = "SELECT activity_id FROM activity_telemetry WHERE athlete_id = :a"

    assert len(_as_runtime(admin_engine, coach_id, read, {"a": athlete_id})) == 3
    # a coach can read, never change, the athlete's recording
    updated = _as_runtime(admin_engine, coach_id,
                          "UPDATE activity_telemetry SET activity_name = 'x' WHERE activity_id = :id", {"id": session})
    assert updated == 0

    with admin_engine.begin() as conn:
        revoked = conn.execute(text("UPDATE consent_grants SET granted = false WHERE athlete_id = :a"),
                               {"a": athlete_id})
        assert revoked.rowcount == 1
    assert _as_runtime(admin_engine, coach_id, read, {"a": athlete_id}) == []

    stranger = _insert_user(admin_engine, email="stranger-day-f@runsense.demo")
    assert _as_runtime(admin_engine, stranger, read, {"a": athlete_id}) == []

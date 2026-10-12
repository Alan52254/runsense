"""DB-dependent tests for the .fit upload: the activity it creates, the
assignment it completes (same day, moved, none), the RunSense helper's
message, and the athlete's correction. Requires TEST_DATABASE_URL; requests
run as runsense_runtime so RLS is exercised. The .fit decoding itself is
replaced by a synthetic recording (app/fit_telemetry.py has its own tests).
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from conftest import requires_db
from tests.test_teams_roster import _insert_consent, _insert_membership, _insert_team, _insert_user
from tests.test_workout_segmentation import EASY, intervals, make_tele

from app import activity_upload

RUN_DAY = date(2026, 10, 9)
INTERVALS = [{"kind": "interval", "label": "間歇", "repetitions": 4, "distanceMeters": 1000,
              "pace": "3:45 /km", "restSeconds": 120}]
EASY_RUN = [{"kind": "jog", "label": "easy run", "durationSeconds": 1800}]


def _fake_fit(plan, *, hour: int, sub_sport: str = "track"):
    tele = make_tele(plan, sub_sport=sub_sport, noise=0.02)
    seconds = tele["samples"]["t"][-1]
    tele.update({
        "start_time": datetime(RUN_DAY.year, RUN_DAY.month, RUN_DAY.day, hour, 0, tzinfo=timezone.utc),
        "device": "synthetic",
        "session": {"timer_s": seconds, "elapsed_s": seconds, "distance_m": tele["samples"]["d"][-1],
                    "avg_hr": 150, "max_hr": 180, "avg_cadence": 85},
    })
    return tele


@pytest.fixture()
def fit(monkeypatch):
    """Upload `tele` as if it were a .fit file: the bytes only key the dedupe."""
    def upload(client, tele, rpe=7):
        monkeypatch.setattr(activity_upload, "parse_fit", lambda _data: tele)
        raw = f"fit-{tele['start_time'].isoformat()}-{uuid.uuid4()}".encode()
        return client.post("/activities/fit-upload",
                           json={"file_base64": base64.b64encode(raw).decode(), "rpe": rpe})
    return upload


def _team(admin_engine, tag: str, *, granted: bool = True):
    team_id = _insert_team(admin_engine, name=f"Upload {tag}")
    coach_id = _insert_user(admin_engine, email=f"coach-up-{tag}@runsense.demo")
    athlete_id = _insert_user(admin_engine, email=f"athlete-up-{tag}@runsense.demo", display_name=f"選手{tag}")
    _insert_membership(admin_engine, team_id=team_id, user_id=coach_id, role="coach", status="ACTIVE")
    _insert_membership(admin_engine, team_id=team_id, user_id=athlete_id, role="athlete", status="ACTIVE")
    if granted:
        _insert_consent(admin_engine, team_id=team_id, athlete_id=athlete_id, scope="activity_summary", granted=True)
    return team_id, coach_id, athlete_id


def _assign(admin_engine, team_id, athlete_id, on: date, structure, title="課表") -> uuid.UUID:
    with admin_engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO assigned_workouts (team_id, athlete_id, local_date, title, duration_minutes, intensity_label, "
            " status, structure) VALUES (:t, :a, :d, :title, 60, '間歇', 'SCHEDULED', CAST(:s AS jsonb)) RETURNING id"),
            {"t": team_id, "a": athlete_id, "d": on, "title": title, "s": json.dumps(structure)}).scalar_one()


def _messages(admin_engine, athlete_id):
    with admin_engine.connect() as conn:
        return conn.execute(text(
            "SELECT m.sender_kind, m.body, m.payload FROM chat_messages m JOIN chat_rooms r ON r.id = m.room_id "
            "WHERE r.athlete_id = :a ORDER BY m.created_at"), {"a": athlete_id}).all()


def _client(make_client, user_id):
    return make_client(actor_id=str(user_id), timezones={str(user_id): "UTC"})


@requires_db
def test_an_upload_completes_that_days_workout_and_tells_the_coach(make_client, admin_engine, fit):
    team_id, coach_id, athlete_id = _team(admin_engine, "a")
    assignment = _assign(admin_engine, team_id, athlete_id, RUN_DAY, INTERVALS, "1000×4")

    response = fit(_client(make_client, athlete_id), _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["day_role"] == "main" and body["signature_label"] == "4 × 1000m"
    assert body["assignment"]["id"] == str(assignment) and body["notified_teams"] == 1

    [(kind, text_, payload)] = _messages(admin_engine, athlete_id)
    assert kind == "ai" and payload["kind"] == "activity_uploaded"
    assert "教練課表：1000×4" in text_ and payload["activity_id"] == body["activity_id"]

    # the coach's list now shows it done
    listing = _client(make_client, coach_id).get(f"/teams/{team_id}/assignments").json()["items"]
    row = next(r for r in listing if r["id"] == str(assignment))
    assert row["status"] == "COMPLETED" and row["completed_on"] == str(RUN_DAY)


@requires_db
def test_a_moved_workout_is_matched_by_its_reps_and_distances(make_client, admin_engine, fit):
    team_id, coach_id, athlete_id = _team(admin_engine, "b")
    planned = date(2026, 10, 8)
    assignment = _assign(admin_engine, team_id, athlete_id, planned, INTERVALS, "1000×4")
    _assign(admin_engine, team_id, athlete_id, date(2026, 10, 10), [
        {"kind": "interval", "label": "間歇", "repetitions": 6, "distanceMeters": 400}], "400×6")

    body = fit(_client(make_client, athlete_id), _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10)).json()
    assert body["assignment"]["id"] == str(assignment)
    [(_k, text_, _p)] = _messages(admin_engine, athlete_id)
    assert "改在這天練" in text_

    listing = _client(make_client, coach_id).get(f"/teams/{team_id}/assignments").json()["items"]
    row = next(r for r in listing if r["id"] == str(assignment))
    assert row["status"] == "COMPLETED" and row["completed_on"] == str(RUN_DAY) and row["local_date"] == str(planned)
    # the coach's view of that assignment opens the day it was run
    day = _client(make_client, coach_id).get(
        f"/teams/{team_id}/athletes/{athlete_id}/training-day",
        params={"local_date": str(planned), "assignment_id": str(assignment)}).json()
    assert day["local_date"] == str(RUN_DAY) and day["main_activity_id"] == body["activity_id"]


@requires_db
def test_no_matching_workout_is_training_of_the_athletes_own(make_client, admin_engine, fit):
    team_id, _coach_id, athlete_id = _team(admin_engine, "c")
    _assign(admin_engine, team_id, athlete_id, date(2026, 10, 8), [
        {"kind": "interval", "label": "間歇", "repetitions": 6, "distanceMeters": 400}], "400×6")
    _assign(admin_engine, team_id, athlete_id, date(2026, 10, 1), INTERVALS, "1000×4 too long ago")

    body = fit(_client(make_client, athlete_id), _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10)).json()
    assert body["assignment"] is None
    [(_k, text_, _p)] = _messages(admin_engine, athlete_id)
    assert "記為自主訓練" in text_


@requires_db
def test_warm_up_and_cool_down_are_announced_but_never_matched(make_client, admin_engine, fit):
    team_id, _coach_id, athlete_id = _team(admin_engine, "d")
    _assign(admin_engine, team_id, athlete_id, RUN_DAY, EASY_RUN, "easy")
    client = _client(make_client, athlete_id)
    fit(client, _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10))

    cool = fit(client, _fake_fit([("steady", 900, EASY)], hour=11, sub_sport="generic")).json()
    assert cool["day_role"] == "cooldown" and cool["assignment"] is None
    assert len(_messages(admin_engine, athlete_id)) == 2
    assert "收操" in _messages(admin_engine, athlete_id)[-1][1]


@requires_db
def test_without_the_activity_summary_scope_there_is_no_message(make_client, admin_engine, fit):
    team_id, _coach_id, athlete_id = _team(admin_engine, "e", granted=False)
    assignment = _assign(admin_engine, team_id, athlete_id, RUN_DAY, INTERVALS)

    body = fit(_client(make_client, athlete_id), _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10)).json()
    assert body["notified_teams"] == 0 and body["assignment"]["id"] == str(assignment)
    assert _messages(admin_engine, athlete_id) == []


@requires_db
def test_the_same_run_cannot_be_uploaded_twice(make_client, admin_engine, fit):
    _team_id, _coach_id, athlete_id = _team(admin_engine, "f")
    client = _client(make_client, athlete_id)
    tele = _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10)
    assert fit(client, tele).status_code == 201
    again = fit(client, tele)
    assert again.status_code == 409 and again.json()["detail"]["error"] == "ACTIVITY_ALREADY_EXISTS"


@requires_db
def test_the_athlete_corrects_the_match(make_client, admin_engine, fit):
    team_id, coach_id, athlete_id = _team(admin_engine, "g")
    same_day = _assign(admin_engine, team_id, athlete_id, RUN_DAY, INTERVALS, "today")
    other = _assign(admin_engine, team_id, athlete_id, date(2026, 10, 11), INTERVALS, "in two days")
    client = _client(make_client, athlete_id)
    activity_id = fit(client, _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10)).json()["activity_id"]

    options = client.get(f"/activities/{activity_id}/assignment").json()
    assert options["current"]["id"] == str(same_day) and options["current"]["linked_by"] == "auto"
    assert {c["id"] for c in options["candidates"]} == {str(same_day), str(other)}

    assert client.put(f"/activities/{activity_id}/assignment",
                      json={"assigned_workout_id": str(other)}).status_code == 200
    listing = _client(make_client, coach_id).get(f"/teams/{team_id}/assignments").json()["items"]
    status = {r["id"]: r["status"] for r in listing}
    assert status[str(other)] == "COMPLETED" and status[str(same_day)] == "SCHEDULED"
    client = _client(make_client, athlete_id)  # make_client overrides the actor app-wide

    cleared = client.put(f"/activities/{activity_id}/assignment", json={"assigned_workout_id": None})
    assert cleared.status_code == 200, cleared.text
    assert client.get(f"/activities/{activity_id}/assignment").json()["current"] is None

    # nothing outside the window, and nothing that is someone else's
    far = _assign(admin_engine, team_id, athlete_id, date(2026, 10, 20), INTERVALS)
    rejected = client.put(f"/activities/{activity_id}/assignment", json={"assigned_workout_id": str(far)})
    assert rejected.status_code == 422


@requires_db
def test_a_deleted_run_no_longer_completes_its_workout(make_client, admin_engine, fit):
    team_id, coach_id, athlete_id = _team(admin_engine, "h")
    assignment = _assign(admin_engine, team_id, athlete_id, RUN_DAY, INTERVALS)
    client = _client(make_client, athlete_id)
    activity_id = fit(client, _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10)).json()["activity_id"]

    assert client.delete(f"/activities/{activity_id}").status_code in (200, 204)
    listing = _client(make_client, coach_id).get(f"/teams/{team_id}/assignments").json()["items"]
    assert next(r for r in listing if r["id"] == str(assignment))["status"] == "SCHEDULED"


@requires_db
def test_an_athlete_cannot_link_a_team_mates_workout(admin_engine, fit, make_client):
    team_id, _coach_id, athlete_id = _team(admin_engine, "i")
    mate = _insert_user(admin_engine, email="mate-up-i@runsense.demo")
    _insert_membership(admin_engine, team_id=team_id, user_id=mate, role="athlete", status="ACTIVE")
    mates_workout = _assign(admin_engine, team_id, mate, RUN_DAY, INTERVALS)
    activity_id = fit(_client(make_client, athlete_id),
                      _fake_fit(intervals(4, 1000, 4.5, 120, 0.0), hour=10)).json()["activity_id"]

    with admin_engine.connect() as conn:
        conn.execute(text("SET ROLE runsense_runtime"))
        conn.commit()
        with pytest.raises(Exception):
            with conn.begin():
                conn.execute(text("SELECT set_config('app.actor_user_id', :a, true)"), {"a": str(athlete_id)})
                conn.execute(text(
                    "INSERT INTO assignment_completions (assigned_workout_id, activity_id, athlete_id, "
                    " activity_local_date, linked_by) VALUES (:w, :id, :a, :d, 'athlete')"),
                    {"w": mates_workout, "id": activity_id, "a": athlete_id, "d": RUN_DAY})
        conn.execute(text("RESET ROLE"))
        conn.commit()

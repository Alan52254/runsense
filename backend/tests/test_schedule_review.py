"""Coach Review of a Schedule Draft, against the database: only the
Assignment Service writes, every reviewed day leaves a decision, a draft the
world moved under is refused, and a retrospective review publishes nothing."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import text

from app import assignment_service
from app.errors import AuthorizationError
from conftest import requires_db
from test_coach_handoff import _daily_runs, _grant, _setup


def _week_setup(admin_engine):
    team_id, coach_id, athlete_id = _setup(admin_engine)
    with admin_engine.begin() as conn:
        conn.execute(text("INSERT INTO athlete_profiles (user_id, timezone) VALUES (:a, 'UTC')"), {"a": athlete_id})
    _daily_runs(admin_engine, athlete_id)
    for scope in ("training_load", "injury_status", "activity_summary"):
        _grant(admin_engine, team_id, athlete_id, scope)
    return team_id, coach_id, athlete_id


def _room(make_client, coach_id, athlete_id) -> str:
    rooms = make_client(actor_id=str(coach_id)).get("/chat/rooms").json()["rooms"]
    return next(r["id"] for r in rooms if r["kind"] == "direct" and r["athlete_id"] == str(athlete_id))


def _decisions(admin_engine, athlete_id):
    with admin_engine.begin() as conn:
        return conn.execute(text("SELECT local_date, source, outcome, changed_fields, published FROM "
                                 "assignment_decisions WHERE athlete_id=:a ORDER BY local_date"),
                            {"a": athlete_id}).all()


@requires_db
def test_a_reviewed_draft_publishes_through_the_service_and_records_each_day(make_client, admin_engine):
    _, coach_id, athlete_id = _week_setup(admin_engine)
    coach = lambda: make_client(actor_id=str(coach_id))  # noqa: E731
    room = _room(make_client, coach_id, athlete_id)

    card = coach().post(f"/chat/rooms/{room}/schedule-draft", json={})
    assert card.status_code == 201, card.text
    payload = card.json()["payload"]
    days = payload["plan"]["days"]
    assert len(days) >= 3 and not payload["schedule_draft"]["review_only"]

    # shorten one day, drop another, keep the rest as suggested
    edited, removed = dict(days[0]), dict(days[1])
    edited["items"] = [dict(edited["items"][0])]
    block = dict(edited["items"][0]["variants"]["all"][0], duration_s=1200)
    edited["items"][0]["variants"] = {"all": [block]}
    removed["removed"] = True
    put = coach().put(f"/chat/cards/{card.json()['id']}", json={"days": [edited, removed]})
    assert put.status_code == 200, put.text
    assert put.json()["payload"]["plan"]["days"][0]["items"][0]["notes"]  # reasons survive an edit

    confirmed = coach().post(f"/chat/cards/{card.json()['id']}/confirm-plan", json={})
    assert confirmed.status_code == 200, confirmed.text
    with admin_engine.begin() as conn:
        written = conn.execute(text("SELECT count(DISTINCT local_date) FROM assigned_workouts WHERE athlete_id=:a"),
                               {"a": athlete_id}).scalar_one()
    assert written == len(days) - 1
    outcomes = {r.local_date.isoformat(): r for r in _decisions(admin_engine, athlete_id)}
    assert outcomes[days[0]["date"]].outcome == "edited" and outcomes[days[0]["date"]].changed_fields == ["時長"]
    assert outcomes[days[1]["date"]].outcome == "removed"
    assert outcomes[days[2]["date"]].outcome == "accepted"
    assert {r.source for r in outcomes.values()} == {"review_card"} and all(r.published for r in outcomes.values())


@requires_db
def test_a_new_injury_report_makes_the_draft_stale(make_client, admin_engine):
    _, coach_id, athlete_id = _week_setup(admin_engine)
    coach = lambda: make_client(actor_id=str(coach_id))  # noqa: E731
    card = coach().post(f"/chat/rooms/{_room(make_client, coach_id, athlete_id)}/schedule-draft", json={}).json()
    tomorrow = date.today() + timedelta(days=1)
    with admin_engine.begin() as conn:
        conn.execute(text(
            """INSERT INTO injury_reports (athlete_id, client_mutation_id, request_fingerprint, has_issue,
                 severity_band, body_part, reported_at, timezone_snapshot, local_training_date)
               VALUES (:a, :c, 'f', true, 'MODERATE', '右小腿', now(), 'UTC', :d)"""),
            {"a": athlete_id, "c": uuid.uuid4(), "d": tomorrow})

    refused = coach().post(f"/chat/cards/{card['id']}/confirm-plan", json={})
    assert refused.status_code == 409 and refused.json()["detail"]["error"] == "DRAFT_STALE"
    # still stale on a second try, and nothing was written either time
    assert coach().post(f"/chat/cards/{card['id']}/confirm-plan", json={}).status_code == 409
    with admin_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM assigned_workouts")).scalar_one() == 0


@requires_db
def test_a_retrospective_review_only_records_and_never_sees_its_own_week(make_client, admin_engine):
    _, coach_id, athlete_id = _week_setup(admin_engine)
    coach = lambda: make_client(actor_id=str(coach_id))  # noqa: E731
    start = date.today() - timedelta(days=14)
    card = coach().post(f"/chat/rooms/{_room(make_client, coach_id, athlete_id)}/schedule-draft",
                        json={"start": start.isoformat()})
    assert card.status_code == 201, card.text
    draft = card.json()["payload"]["schedule_draft"]
    assert draft["review_only"]
    # the athlete ran every one of those days, but the draft was built as of
    # the start date: nothing inside its week is known yet
    assert "locked" not in {d["action"] for d in draft["week"]}

    assert coach().post(f"/chat/cards/{card.json()['id']}/confirm-plan", json={}).status_code == 409
    recorded = coach().post(f"/chat/cards/{card.json()['id']}/record-review", json={"reason": "回溯審核"})
    assert recorded.status_code == 200, recorded.text
    with admin_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM assigned_workouts")).scalar_one() == 0
    rows = _decisions(admin_engine, athlete_id)
    assert rows and all(r.source == "retrospective_review" and not r.published for r in rows)


@requires_db
def test_a_manual_assignment_is_recorded_as_coach_authored(make_client, admin_engine):
    team_id, coach_id, athlete_id = _week_setup(admin_engine)
    day = date.today() + timedelta(days=3)
    created = make_client(actor_id=str(coach_id)).post(f"/teams/{team_id}/assignments", json={
        "athlete_id": str(athlete_id), "local_date": day.isoformat(), "title": "6 × 1000m",
        "duration_minutes": 60, "intensity_label": "間歇", "structure": []})
    assert created.status_code == 201, created.text
    (row,) = _decisions(admin_engine, athlete_id)
    assert (row.local_date, row.source, row.outcome, row.published) == (day, "manual_assignment",
                                                                         "coach_authored", True)


@requires_db
def test_assignment_service_itself_rejects_a_non_coach(admin_engine):
    team_id, _, athlete_id = _week_setup(admin_engine)
    day = date.today() + timedelta(days=3)
    with admin_engine.begin() as conn:
        try:
            assignment_service.publish(
                conn, actor_id=athlete_id, team_id=team_id, source="manual_assignment",
                days=[assignment_service.DayWrite(athlete_id, "選手", day, ({
                    "title": "輕鬆跑", "duration_minutes": 30, "intensity_label": "輕鬆",
                    "structure": [], "tracked": True, "notes": None},))])
        except AuthorizationError:
            pass
        else:
            raise AssertionError("Assignment Service accepted a non-coach actor")




@requires_db
def test_the_team_review_page_shows_each_athletes_week(make_client, admin_engine):
    team_id, coach_id, athlete_id = _week_setup(admin_engine)
    coach = lambda: make_client(actor_id=str(coach_id))  # noqa: E731
    before = coach().get(f"/teams/{team_id}/schedule-review")
    assert before.status_code == 200, before.text
    (row,) = before.json()["athletes"]
    assert row["status"] == "not_built" and row["shares_load"] and row["observation_days"]

    coach().post(f"/chat/rooms/{row['room_id']}/schedule-draft", json={})
    (row,) = coach().get(f"/teams/{team_id}/schedule-review").json()["athletes"]
    assert row["status"] == "pending" and row["draft"]["changes"] > 0 and row["draft"]["outcomes"] == {}
    # only the team's coach may look
    assert make_client(actor_id=str(athlete_id)).get(f"/teams/{team_id}/schedule-review").status_code == 403

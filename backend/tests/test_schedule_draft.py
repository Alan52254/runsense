"""The week a Coach reviews: every input decided in one place, the engine
choosing every workout, and nothing the Coach scheduled overwritten."""

from __future__ import annotations

from datetime import date, timedelta

from app.schedule_draft import (
    AnalysisAdvice,
    AthleteStatement,
    Assignment,
    InjuryFact,
    PlanningSnapshot,
    card_payload,
    day_weather,
    plan_week,
)

START = date(2026, 8, 10)  # a Monday in a hot Taipei August


def _snap(**kw) -> PlanningSnapshot:
    base = dict(athlete_id="a", start=START, days=7, sex="male", city=None, acute_load=300.0,
                chronic_load=300.0, observation_days=28, weather={}, injuries=(), statements={},
                assignments={}, completed=frozenset(), analysis=None)
    base.update(kw)
    return PlanningSnapshot(**base)


def _by_date(week):
    return {d["date"]: d for d in week}


def _assign(day: date, title: str, intensity: str) -> dict:
    return {day: (Assignment(day, title, intensity, 60),)}


def test_every_day_is_planned_and_only_the_engine_sets_workouts():
    week = plan_week(_snap())
    assert [d["date"] for d in week] == [(START + timedelta(days=i)).isoformat() for i in range(7)]
    for d in week:
        if d["proposed"]:
            assert d["proposed"]["workout_type"] in {"REST_DAY", "RECOVERY_RUN", "EASY_RUN", "STEADY_RUN",
                                                     "REST_AND_SEEK_CARE"}


def test_completed_days_are_locked_and_coach_assignments_kept():
    tue = START + timedelta(days=1)
    week = _by_date(plan_week(_snap(completed=frozenset({START}),
                                    assignments=_assign(tue, "8 × 400m", "間歇"))))
    assert week[START.isoformat()]["action"] == "locked"
    assert week[tue.isoformat()]["action"] == "keep"
    assert week[tue.isoformat()]["proposed"] is None


def test_injury_turns_a_hard_coach_day_into_a_gentler_proposal_for_the_coach():
    tue = START + timedelta(days=1)
    week = _by_date(plan_week(_snap(injuries=(InjuryFact(START, "MILD", "右小腿"),),
                                    assignments=_assign(tue, "8 × 400m", "間歇"))))
    day = week[tue.isoformat()]
    assert day["action"] == "adjust"
    assert day["proposed"]["workout_type"] in {"REST_DAY", "RECOVERY_RUN"}  # self-care triage ladder
    assert any(r["kind"] == "injury" and "右小腿" in r["text"] for r in day["reasons"])


def test_an_old_injury_stops_applying():
    late = START + timedelta(days=5)
    week = _by_date(plan_week(_snap(injuries=(InjuryFact(START, "MILD", "右小腿"),))))
    assert not any(r["kind"] == "injury" for r in week[late.isoformat()]["reasons"])


def test_no_hard_day_next_to_a_coach_interval_day():
    wed = START + timedelta(days=2)
    week = _by_date(plan_week(_snap(assignments=_assign(wed, "6 × 1000m", "間歇"))))
    for neighbour in (START + timedelta(days=1), START + timedelta(days=3)):
        day = week[neighbour.isoformat()]
        if day["proposed"]:
            assert day["proposed"]["workout_type"] != "STEADY_RUN"


def test_what_the_athlete_told_the_health_coach_shapes_that_day():
    thu = START + timedelta(days=3)
    week = _by_date(plan_week(_snap(statements={thu: AthleteStatement(thu, 25, None, None, "只有 25 分鐘")})))
    day = week[thu.isoformat()]
    assert day["proposed"]["duration_minutes"] <= 25
    assert any(r["kind"] == "health_coach" and "25 分鐘" in r["text"] for r in day["reasons"])


def test_weather_picks_the_cooler_window_and_is_labelled_an_estimate():
    w = day_weather("Taipei", "male", START)
    assert w is not None and w.source == "climate"
    best = w.best()
    assert best[0] in ("morning", "evening")
    week = plan_week(_snap(city="Taipei", weather={START + timedelta(days=i): day_weather("Taipei", "male",
                                                                                          START + timedelta(days=i))
                                                   for i in range(7)}))
    notes = [r["text"] for d in week for r in d["reasons"] if r["kind"] == "weather"]
    assert notes and all("氣候估計" in n for n in notes)


def test_analysis_advice_goes_to_the_next_hard_coach_session_once():
    tue, fri = START + timedelta(days=1), START + timedelta(days=4)
    assignments = {**_assign(tue, "8 × 400m", "間歇"), **_assign(fri, "節奏跑 6 km", "節奏跑")}
    advice = AnalysisAdvice(START - timedelta(days=3), "4x1000m", ("第一趟壓在 4:05/km",))
    week = _by_date(plan_week(_snap(assignments=assignments, analysis=advice)))
    assert any(r["kind"] == "analysis" for r in week[tue.isoformat()]["reasons"])
    assert not any(r["kind"] == "analysis" for r in week[fri.isoformat()]["reasons"])


def test_card_holds_only_proposed_running_days_and_carries_notes():
    tue = START + timedelta(days=1)
    snap = _snap(assignments=_assign(tue, "8 × 400m", "間歇"), completed=frozenset({START}))
    week = plan_week(snap)
    payload = card_payload(snap, week, {"id": "a", "name": "倫敦選手", "sex": "male"}, version=2, today=START)
    proposed = {d["date"] for d in week if d["action"] in ("add", "adjust")
                and d["proposed"]["running_allowed"] and d["proposed"]["duration_minutes"]}
    assert {d["date"] for d in payload["plan"]["days"]} == proposed
    assert START.isoformat() not in proposed and tue.isoformat() not in proposed
    assert payload["schedule_draft"]["version"] == 2
    assert len(payload["schedule_draft"]["week"]) == 7


def test_too_little_recent_data_leaves_the_day_to_the_coach_not_rest():
    week = plan_week(_snap(acute_load=0.0, chronic_load=0.0, observation_days=0))
    assert {d["action"] for d in week} == {"open"}
    assert all(d["proposed"] is None for d in week)

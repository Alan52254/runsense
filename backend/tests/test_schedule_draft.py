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
    assert w is not None and w.source == "climate_estimate"
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


# ---------------------------------------------------------------- pace, forecast, review

from app.schedule_draft import apply_weather_update, decide, fingerprint, revalidate  # noqa: E402
from app.weather_forecast import HourlyForecast  # noqa: E402


def _hot_forecast(temp: float) -> HourlyForecast:
    hours = {}
    for i in range(7):
        d = START + timedelta(days=i)
        for h, t in ((6, temp - 4), (12, temp + 4), (18, temp)):
            hours[(d, h)] = (t, 70.0, 8.0)
    return HourlyForecast("open-meteo", "2026-08-10T00:00:00+00:00", hours)


def _weekly(snap_kw=None, temp=30.0):
    weather = {START + timedelta(days=i): day_weather("Taipei", "male", START + timedelta(days=i),
                                                      forecast=_hot_forecast(temp)) for i in range(7)}
    return _snap(city="Taipei", weather=weather, easy_pace_s_per_km=330, **(snap_kw or {}))


def test_a_real_forecast_is_used_and_labelled_as_one():
    w = day_weather("Taipei", "male", START, forecast=_hot_forecast(30.0))
    assert w.source == "forecast" and w.provider == "open-meteo" and w.fetched_at
    first = w.as_dict()["windows"][0]
    assert first["valid_at"] == "2026-08-10T06:00:00"
    assert first["humidity_pct"] == 70.0 and first["wind_kph"] == 8.0
    notes = [r["text"] for d in plan_week(_weekly()) for r in d["reasons"] if r["kind"] == "weather"]
    assert notes and all("預報" in n and "氣候估計" not in n for n in notes)


def test_suggested_runs_carry_a_heat_adjusted_pace_from_the_athletes_own_easy_pace():
    snap = _weekly()
    week = plan_week(snap)
    card = card_payload(snap, week, {"id": "a", "name": "A", "sex": "male"}, version=1, today=START)
    block = card["plan"]["days"][0]["items"][0]["variants"]["all"][0]
    assert block["target_s_per_km"] and "–" in block["target_text"]
    cool = plan_week(_weekly(temp=18.0))
    hot_pace = next(d["proposed"]["pace_range"] for d in week if d["proposed"])
    cool_pace = next(d["proposed"]["pace_range"] for d in cool if d["proposed"])
    assert hot_pace[1] >= cool_pace[1]  # heat only ever slows the band


def test_no_easy_pace_baseline_means_no_pace_not_a_guess():
    snap = _snap()
    week = plan_week(snap)
    day = next(d for d in week if d["proposed"])
    assert day["proposed"]["pace_range"] is None
    assert any(r["kind"] == "pace" and "不足" in r["text"] for r in day["reasons"])


def test_decisions_tell_accepted_edited_removed_authored_and_insufficient_apart():
    week = [
        {"date": "2026-08-10", "action": "add"}, {"date": "2026-08-11", "action": "add"},
        {"date": "2026-08-12", "action": "add"}, {"date": "2026-08-13", "action": "open"},
        {"date": "2026-08-14", "action": "open"}, {"date": "2026-08-15", "action": "keep"},
    ]

    def day(key, d, minutes, removed=False, suggested=True, kind="easy"):
        block = {"duration_s": minutes * 60, "distance_m": 7000, "target_s_per_km": 340}
        return {"key": key, "date": d, "removed": removed,
                "items": [{"type": "run", "kind": kind, "title": "t", "variants": {"all": [block]}}],
                "suggested": {"date": d, "kind": "easy", "title": "t",
                              "block": {"duration_s": 2400, "distance_m": 7000, "target_s_per_km": 340}}
                if suggested else None}

    plan = [day("d0", "2026-08-10", 40), day("d1", "2026-08-11", 30), day("d2", "2026-08-12", 40, removed=True),
            day("n1", "2026-08-13", 50, suggested=False)]
    plan[1]["review_reason"] = "縮短以配合恢復"
    out = {d["date"]: d for d in decide(week, plan, reason="膝蓋還在恢復")}
    assert out["2026-08-10"]["outcome"] == "accepted"
    assert out["2026-08-11"]["outcome"] == "edited" and out["2026-08-11"]["changed"] == ["時長"]
    assert out["2026-08-11"]["reason"] == "縮短以配合恢復"
    assert out["2026-08-12"]["outcome"] == "removed"
    assert out["2026-08-13"]["outcome"] == "coach_authored"
    assert out["2026-08-14"]["outcome"] == "insufficient_data"
    assert "2026-08-15" not in out  # the coach's own day was never a suggestion


def test_revalidate_blocks_on_injury_completion_assignment_load_and_pace():
    base = fingerprint(_weekly())
    assert revalidate(base, base, [])["blocking"] == []
    worse = dict(base, injuries=[["2026-08-11", "MODERATE"]], completed=["2026-08-10"],
                 assignments={"2026-08-12": [{"title": "6 × 1000m", "intensity_label": "間歇",
                                                "duration_minutes": 60, "structure": []}]},
                 load_band="very_high", easy_pace=345)
    kinds = {b["kind"] for b in revalidate(base, worse, [])["blocking"]}
    assert kinds == {"injury", "completed", "assigned", "load", "pace"}


def test_revalidate_blocks_on_any_pace_baseline_or_assignment_detail_change():
    base = fingerprint(_weekly())
    pace_changed = dict(base, easy_pace=base["easy_pace"] + 1)
    assignment_changed = dict(base, assignments={
        "2026-08-12": [{"title": "輕鬆跑", "intensity_label": "輕鬆", "duration_minutes": 50,
                        "structure": []}],
    })
    assert {b["kind"] for b in revalidate(base, pace_changed, [])["blocking"]} == {"pace"}
    assert {b["kind"] for b in revalidate(base, assignment_changed, [])["blocking"]} == {"assigned"}


def test_a_moved_forecast_is_offered_as_a_pace_update_not_a_block():
    hot, cool = _weekly(temp=34.0), _weekly(temp=24.0)
    week = plan_week(hot)
    card = card_payload(hot, week, {"id": "a", "name": "A", "sex": "male"}, version=1, today=START)
    check = revalidate(fingerprint(hot), fingerprint(cool), card["plan"]["days"])
    assert check["blocking"] == [] and check["weather"]
    first = check["weather"][0]
    apply_weather_update(card["plan"]["days"], check["weather"])
    day = next(d for d in card["plan"]["days"] if d["key"] == first["key"])
    assert day["items"][0]["variants"]["all"][0]["target_text"] == first["now"]["pace"]


def test_card_keeps_an_immutable_copy_of_the_original_system_plan():
    snap = _weekly()
    card = card_payload(snap, plan_week(snap), {"id": "a", "name": "A", "sex": "male"},
                        version=1, today=START)
    original = card["schedule_draft"]["original_plan"]["days"][0]["items"][0]["title"]
    card["plan"]["days"][0]["items"][0]["title"] = "教練修改"
    assert card["schedule_draft"]["original_plan"]["days"][0]["items"][0]["title"] == original


def test_weather_source_downgrade_is_shown_even_when_loss_difference_is_small():
    snap = _weekly(temp=24.0)
    card = card_payload(snap, plan_week(snap), {"id": "a", "name": "A", "sex": "male"},
                        version=1, today=START)
    old = fingerprint(snap)
    new = {**old, "weather": {d: {**w, "source": "climate_estimate", "provider": None}
                              for d, w in old["weather"].items()}}
    assert revalidate(old, new, card["plan"]["days"])["weather"]

"""Deterministic parts of the team chat's @AI helper."""

from __future__ import annotations

from datetime import date

from app.chat_plan import _build, day_blocking_problems, resolve_date
from app.chat_service import keyword_red_flags, pace_facts, severity_from_score, triage_for

TODAY = date(2026, 10, 9)  # a Friday


def test_dates_without_a_year_are_the_next_occurrence():
    assert resolve_date({"date": "10/12"}, TODAY)[0] == date(2026, 10, 12)
    assert resolve_date({"date": "9/14"}, TODAY)[0] == date(2027, 9, 14)


def test_weekday_inside_a_written_week():
    d, _hint = resolve_date({"weekday": "四", "week_range": "10/12～10/18"}, TODAY)
    assert d == date(2026, 10, 15)


def test_relative_dates():
    assert resolve_date({"relative": "明天"}, TODAY)[0] == date(2026, 10, 10)
    assert resolve_date({"relative": "下週一"}, TODAY)[0] == date(2026, 10, 12)
    assert resolve_date({}, TODAY)[0] is None


def test_numbers_must_be_in_the_days_own_text_and_sets_expand():
    data = {"days": [{"source": "禮拜一\n200*10 2組 男37內 趟休60S 組休7分鐘", "date": "10/12", "items": [
        {"type": "run", "kind": "intervals", "title": "200×10",
         "variants": {"male": [{"reps": 10, "sets": 2, "distance_m": 200, "target": 37, "target_unit": "per_rep_s",
                                "target_mode": "max", "rest_s": 60, "rest_after_s": 420}]}}]}]}
    plan = _build(data, "禮拜一\n200*10 2組 男37內 趟休60S 組休7分鐘", TODAY)
    blocks = plan["days"][0]["items"][0]["variants"]["male"]
    assert len(blocks) == 2 and blocks[0]["target_s_per_km"] == 185.0 and blocks[0]["target_mode"] == "max"

    invented = {"days": [{"source": "400*8", "date": "10/12", "items": [
        {"type": "run", "kind": "intervals", "title": "400×8",
         "variants": {"all": [{"reps": 8, "distance_m": 400, "target": 75, "target_unit": "per_rep_s"}]}}]}]}
    plan = _build(invented, "400*8", TODAY)
    assert plan["days"] == [] or any("75" in p for p in plan["days"][0]["problems"])


def test_men_women_targets_must_be_split():
    day = {"date": "2026-10-15", "source": "1000*5 男3:30 女4:10",
           "items": [{"type": "run", "title": "1000*5", "variants": {"all": [{"reps": 5}]}}]}
    assert day_blocking_problems(day)
    day["items"][0]["variants"] = {"male": [{"reps": 5}], "female": [{"reps": 5}]}
    assert day_blocking_problems(day) == []


def test_pain_score_mapping():
    assert [severity_from_score(x) for x in (None, 0, 2, 3, 4, 6, 7, 10)] == \
        [None, "NONE", "MILD", "MILD", "MODERATE", "MODERATE", "SEVERE", "SEVERE"]


def test_red_flag_words_reach_the_safety_triage():
    flags = keyword_red_flags("剛跑完胸悶喘不過氣")
    assert flags["chest_pain_or_breathing_difficulty"]
    assert triage_for("MILD", None, flags)["urgency"] == "EMERGENCY"
    assert triage_for("MILD", "小腿", keyword_red_flags("小腿有點緊"))["urgency"] == "SELF_CARE_NEXT_STEP"


def test_pace_conversions_are_computed_not_generated():
    assert pace_facts("400 跑 80 秒等於每公里多少") == ["400m 跑 80 秒 = 每公里 3:20（每 400m 80 秒）"]
    assert "每 400m 90.0 秒" in pace_facts("配速 3:45/km")[0]


def _one_run_day(source: str, block: dict) -> dict:
    return {"days": [{"source": source, "date": "10/17", "items": [
        {"type": "run", "kind": "intervals", "title": "x", "variants": {"all": [block]}}]}]}


def test_sets_keep_the_rep_rest_and_drop_the_rest_after_the_last_set():
    src = "200*10*2 配3:20 組休60 大休7分鐘"
    plan = _build(_one_run_day(src, {"reps": 10, "sets": 2, "distance_m": 200, "target": 200,
                                     "target_unit": "per_km_s", "rest_s": 60, "rest_after_s": 420}), src, TODAY)
    b = plan["days"][0]["items"][0]["variants"]["all"]
    assert [(x["rest_s"], x["rest_after_s"]) for x in b] == [(60, 420), (60, None)]
    assert plan["days"][0]["problems"] == []


def test_a_rest_the_model_dropped_is_flagged():
    # the model left out 組休60: the card must not look complete
    src = "200*10*2 配3:20 組休60 大休7分鐘"
    plan = _build(_one_run_day(src, {"reps": 10, "sets": 2, "distance_m": 200, "target": 200,
                                     "target_unit": "per_km_s", "rest_after_s": 420}), src, TODAY)
    b = plan["days"][0]["items"][0]["variants"]["all"]
    assert [(x["rest_s"], x["rest_after_s"]) for x in b] == [(None, 420), (None, None)]
    assert any("60" in p for p in plan["days"][0]["problems"])


def test_one_set_with_a_trailing_rest_is_the_rep_rest():
    src = "600*8 男80 400m/s 組休3.5min"
    plan = _build(_one_run_day(src, {"reps": 8, "distance_m": 600, "target": 80, "target_unit": "per_400_s",
                                     "rest_after_s": 210}), src, TODAY)
    b = plan["days"][0]["items"][0]["variants"]["all"]
    assert [(x["rest_s"], x["rest_after_s"]) for x in b] == [(210, None)]


def test_card_preview_and_confirm_write_the_same_record():
    from app.chat_service import assignment_record

    item = {"type": "run", "kind": "intervals", "title": "1000*5", "variants": {
        "male": [{"reps": 5, "distance_m": 1000, "target_s_per_km": 210, "target_mode": "exact",
                  "target_text": "3:30/km", "rest_s": 120, "rest_after_s": None}],
        "female": [{"reps": 5, "distance_m": 1000, "target_s_per_km": 250, "target_mode": "exact",
                    "target_text": "4:10/km", "rest_s": 120, "rest_after_s": None}]}}
    male, female = assignment_record(item, "male"), assignment_record(item, "female")
    assert male["structure"][0]["pace"] == "3:30 /km" and female["structure"][0]["pace"] == "4:10 /km"
    assert male["tracked"] and male["duration_minutes"] > 0
    assert assignment_record(item, None) is None  # no variant for this athlete: nothing written
    core = assignment_record({"type": "core", "title": "核心", "content": "棒式 60s*3"}, "male")
    assert core["tracked"] is False and core["notes"] == "棒式 60s*3" and core["structure"] == []

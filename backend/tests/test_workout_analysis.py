"""Coach findings and the narrative's number check, on synthetic sessions."""

from __future__ import annotations

from datetime import date

from app.workout_analysis import _history_findings, analyse_workout, resolve_hr_profile, usual_range
from app.workout_narrative import (build_facts, offline_narrative, signature_label, style_problems,
                                   unverified_numbers)
from app.workout_segmentation import detect_workout
from tests.test_workout_segmentation import EASY, make_tele

DEVICE_HR = {"max_hr": 200, "resting_hr": 55, "hr_calc_type": "percent_hrr",
             "zone_high_bounds": [130, 140, 152, 175, 188, 200]}


def _hr():
    return resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=DEVICE_HR,
                              history_peak_30s=None, birth_year=None, on_date=date(2026, 7, 1))


def _session(rep_speeds, rest_s=120, cooldown_s=480):
    plan = [("warmup", 720, EASY)]
    for i, sp in enumerate(rep_speeds):
        plan.append(("work", round(1000 / sp), sp))
        if i < len(rep_speeds) - 1:
            plan.append(("rest", rest_s, 0.0))
    plan.append(("cooldown", cooldown_s, EASY))
    tele = make_tele(plan, noise=0.02)
    det = detect_workout(tele, EASY)
    return tele, det


def _codes(analysis):
    return {f["code"]: f for f in analysis["findings"]}


def _analyse(rep_speeds, *, target=None, history=None, prescription=None, **session):
    tele, det = _session(rep_speeds, **session)
    return analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=target,
                           hr=_hr(), easy_speed=EASY, history=history, prescription=prescription)


def test_an_inferred_structure_gets_no_pace_verdicts():
    a = _analyse([4.75, 4.5, 4.48, 4.42, 4.38, 4.33])
    codes = _codes(a)
    for code in ("consistency", "first_rep", "pace_trend", "rep_hr", "rest", "warmup", "cooldown"):
        assert code in codes
    # targets inferred from this very run are not graded
    for code in ("consistency", "first_rep", "pace_trend"):
        assert codes[code]["severity"] == "info"
    assert "warning" not in {f["severity"] for f in a["findings"]}
    # what research says cannot be judged on its own, and the warm-up
    assert codes["rep_hr"]["severity"] == "dismiss" and codes["cooldown"]["severity"] == "dismiss"
    assert codes["warmup"]["severity"] == "positive"
    assert all(f["advice"] is None for f in a["findings"] if f["code"] != "progression_structure")
    assert [r["rep_number"] for r in a["reps"]] == [1, 2, 3, 4, 5, 6]


def test_usual_range_needs_two_sessions():
    assert usual_range([1.0]) is None
    assert usual_range([1.0, None]) is None
    rng = usual_range([2.0, 3.0])
    # 2.5 +/- 1.645 x SD 0.707 x sqrt(1 + 1/2)
    assert rng["sessions"] == 2 and abs(rng["mean"] - 2.5) < 1e-9
    assert abs((rng["high"] - rng["mean"]) - 1.645 * 0.70711 * 1.22474) < 1e-3


def test_a_number_is_placed_against_the_athletes_usual_range():
    history = [{"date": d, "signature": "6x1000m", "mean_pace_s_per_km": 222.0, "block_cv_pct": cv}
               for d, cv in (("2026-06-20", 0.10), ("2026-06-13", 0.11), ("2026-06-06", 0.10))]
    a = _analyse([4.75, 4.5, 4.48, 4.42, 4.38, 4.33], history=history)
    assert "高於你過去 3 次同課表的平常範圍" in _codes(a)["consistency"]["detail"]
    without = _analyse([4.75, 4.5, 4.48, 4.42, 4.38, 4.33], history=history[:1])
    assert "平常範圍" not in _codes(without)["consistency"]["detail"]


def test_every_finding_says_what_its_numbers_mean_and_unusual_ones_come_first():
    history = [{"date": d, "signature": "6x1000m", "mean_pace_s_per_km": 222.0, "block_cv_pct": cv}
               for d, cv in (("2026-06-20", 0.10), ("2026-06-13", 0.11), ("2026-06-06", 0.10))]
    a = _analyse([4.75, 4.5, 4.48, 4.42, 4.38, 4.33], history=history)
    codes = _codes(a)
    assert codes["consistency"]["compare"] == "different"
    assert "比你平常大" in codes["consistency"]["meaning"]
    assert codes["warmup"]["compare"] is None and codes["warmup"]["meaning"]
    order = [f["compare"] for f in a["findings"] if f["severity"] == "info"]
    assert order.index("different") < order.index(None)
    for f in a["findings"]:
        if f["code"] not in ("interruption", "linked_warmup", "linked_cooldown", "progression_structure"):
            assert f.get("meaning"), f["code"]


def test_warmup_and_cooldown_are_reported_without_advice():
    codes = _codes(_analyse([4.5] * 4, cooldown_s=120))
    assert 110 <= codes["cooldown"]["evidence"]["seconds"] <= 130  # a 120 s cool-down, boundary jitter aside
    assert codes["cooldown"]["advice"] is None and codes["warmup"]["advice"] is None


def test_an_inferred_structure_is_shown_but_not_graded():
    a = _analyse([4.5] * 5)
    assert a["summary"]["prescription"]["gradable"] is False
    assert "target" not in _codes(a)


def test_an_upper_limit_target_is_met_at_or_under_it():
    blocks = [{"reps": 5, "distance_m": 1000, "duration_s": None, "targets_s_per_km": [225],
               "rest_s": 120, "target_mode": "max"}]
    met = _analyse([4.5] * 5, prescription={"source": "athlete_text", "raw_text": None, "blocks": blocks})
    target = _codes(met)["target"]
    assert target["severity"] == "positive" and target["title"] == "每趟都在要求以內"
    blocks[0]["targets_s_per_km"] = [215]
    missed = _analyse([4.5] * 5, prescription={"source": "athlete_text", "raw_text": None, "blocks": blocks})
    missed_target = _codes(missed)["target"]
    assert missed_target["severity"] == "warning"
    assert missed_target["title"].endswith("超出要求") and "5 趟中有 0 趟在要求以內" in missed_target["detail"]


def _range_prescription(target, tolerance):
    return {"source": "coach_assignment", "raw_text": None,
            "blocks": [{"reps": 5, "distance_m": 1000, "duration_s": None, "targets_s_per_km": [target],
                        "tolerance_s_per_km": tolerance, "rest_s": 120, "target_mode": "exact"}]}


def test_the_coachs_range_is_the_criterion():
    inside = _analyse([4.5] * 5, prescription=_range_prescription(222.5, 2.5))  # 222 s/km in 220-225
    target = _codes(inside)["target"]
    assert target["severity"] == "positive" and target["title"] == "每趟都在目標的容許範圍內"
    assert "教練設定的範圍" in target["detail"]
    assert inside["reps"][0]["target_label"] == "3:40–3:45/km"
    outside = _analyse([4.5] * 5, prescription=_range_prescription(232.5, 2.5))  # 230-235: every rep faster
    target = _codes(outside)["target"]
    assert target["severity"] == "warning" and target["title"].endswith("比目標快")


def test_an_easy_run_is_judged_against_the_top_of_zone_2():
    # synthetic heart rate settles near 95 + 22 x speed; zone 2 tops out at 152 bpm
    def easy(speed):
        tele = make_tele([("steady", 1800, speed)], sub_sport="generic", manual_laps=False, noise=0.02)
        return _codes(analyse_workout(tele, [{"role": "steady", "start_s": 0, "end_s": 1800}], session_type="easy",
                                      target_pace_s_per_km=None, hr=_hr(), easy_speed=EASY))["zone_time"]
    assert easy(3.0)["severity"] == "warning" and easy(3.0)["title"] == "輕鬆跑跑太快"
    assert easy(2.4)["severity"] == "positive"


def test_rest_is_compared_with_the_prescribed_rest():
    blocks = [{"reps": 4, "distance_m": 1000, "duration_s": None, "targets_s_per_km": [222],
               "rest_s": 90}]
    a = _analyse([4.5] * 4, prescription={"source": "athlete_text", "raw_text": None, "blocks": blocks})
    rest = _codes(a)["rest"]
    assert "課表要求 1:30（長 30 秒）" in rest["detail"]
    assert rest["severity"] == "warning" and rest["title"] == "休息比課表長"


def test_rep_pace_uses_the_confirmed_nominal_distance():
    tele, det = _session([4.5] * 4)
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=None,
                        hr=_hr(), easy_speed=EASY)
    for r in a["reps"]:
        assert r["distance_m"] == 1000
        assert abs(r["pace_s_per_km"] - r["moving_s"]) < 1e-6


def test_an_exact_target_is_judged_against_the_default_tolerance():
    # 1000 m at 222 s/km: tolerance max(0.57 %, 1 s / 240 s) = 0.57 %
    off = _analyse([4.5] * 5, target=240)
    target = _codes(off)["target"]
    assert target["severity"] == "warning" and target["title"].endswith("比目標快")
    assert "容許範圍約 ±0.6%" in target["detail"] and target["advice"]
    on = _analyse([4.5] * 5, target=222)
    codes = _codes(on)
    assert codes["target"]["severity"] == "positive"
    assert codes["consistency"]["severity"] == "positive" and codes["first_rep"]["severity"] == "positive"


def test_a_fast_start_and_a_fade_against_the_target():
    a = _analyse([4.75, 4.5, 4.48, 4.42, 4.38, 4.33], target=222)
    codes = _codes(a)
    assert codes["first_rep"]["title"] == "第一趟太快"
    assert "後段掉速" in codes["pace_trend"]["title"] and codes["pace_trend"]["severity"] == "warning"
    assert codes["consistency"]["title"] == "每趟離目標忽快忽慢"
    # what needs work comes first
    assert a["findings"][0]["severity"] == "warning"


def test_hr_profile_priority():
    on = date(2026, 7, 1)
    manual = resolve_hr_profile(manual_max_hr=198, manual_resting_hr=None, device=DEVICE_HR,
                                history_peak_30s=203, birth_year=2005, on_date=on)
    assert (manual.max_hr, manual.max_hr_source) == (198, "manual")
    # the watch's own zone percentages are kept, re-applied to the manual max
    assert manual.zone_tops[-1] == 198
    device = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=DEVICE_HR,
                                history_peak_30s=203, birth_year=2005, on_date=on)
    assert (device.max_hr, device.max_hr_source, device.zone_tops) == (200, "device", DEVICE_HR["zone_high_bounds"])
    history = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device={},
                                 history_peak_30s=203, birth_year=2005, on_date=on)
    assert (history.max_hr, history.max_hr_source) == (203, "history")
    age = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device={},
                             history_peak_30s=None, birth_year=2005, on_date=on)
    assert (age.max_hr, age.max_hr_source) == (193, "age_formula")  # 208 - 0.7 x 21


def test_narrative_number_check_rejects_invented_numbers():
    tele, det = _session([4.6, 4.5, 4.5, 4.45])
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=None,
                        hr=_hr(), easy_speed=EASY)
    facts = build_facts(signature_label="4 × 1000m", session_type="intervals", activity_date="2026-07-01",
                        analysis=a, sub_sport="track")
    first_pace = facts["每趟"][0]["配速"].split("/")[0]
    ok = f"第 1 趟 {first_pace}/km，第 3 趟也很穩。"
    assert unverified_numbers(ok, facts, rep_count=4) == []
    assert unverified_numbers("第 2 趟其實跑了 3:01/km，心率 231 bpm", facts, rep_count=4) == ["231", "3:01"]


def test_offline_narrative_reads_like_a_coach_and_only_uses_known_numbers():
    tele, det = _session([4.75, 4.5, 4.48, 4.42, 4.38, 4.33])
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=None,
                        hr=_hr(), easy_speed=EASY)
    facts = build_facts(signature_label="6 × 1000m", session_type="intervals", activity_date="2026-07-01",
                        analysis=a, sub_sport="track")
    text = offline_narrative(facts)
    assert style_problems(text) == []
    assert text.strip().splitlines()[-1].startswith("下次：")
    assert unverified_numbers(text, facts, rep_count=6) == []


def test_style_check_flags_report_shape_and_empty_praise():
    assert style_problems("第 1 趟 4:20/km，比要求快 5 秒。\n\n下次：第一趟壓在 4:25/km。") == []
    problems = style_problems("### 表現總評\n整體而言做得很好，繼續保持！")
    assert "用了標題" in problems
    assert any("做得很好" in p for p in problems)
    assert "缺少「下次：」那一行" in problems
    assert style_problems("第 1 趟太快，導致後段掉速。\n\n下次：照目標跑。") == ["自行加上因果「導致」"]


def test_recovery_is_not_judged_without_the_athletes_own_history():
    summary = {"mean_work_pace_s_per_km": 250.0, "mean_rep_hr": 170, "mean_hr_drop": 18}
    findings = []
    _history_findings(summary, [{"date": "2026-06-20", "signature": "6x1000m", "mean_pace_s_per_km": 252.0,
                                 "mean_rep_hr": 171, "mean_hr_drop": None}], findings)
    assert "recovery_trend" not in {f["code"] for f in findings}


def test_recovery_change_is_read_against_hrr60_measurement_error():
    # two earlier sessions: margin = 1.645 x 10.9 % x sqrt(1 + 1/2) = 22.0 %
    history = [{"date": d, "signature": "6x1000m", "mean_pace_s_per_km": 250.0, "mean_rep_hr": 170,
                "mean_hr_drop": 32} for d in ("2026-06-20", "2026-06-06")]
    slow, same = [], []
    _history_findings({"mean_work_pace_s_per_km": 250.0, "mean_rep_hr": 170, "mean_hr_drop": 20}, history, slow)
    _history_findings({"mean_work_pace_s_per_km": 250.0, "mean_rep_hr": 170, "mean_hr_drop": 30}, history, same)
    slow_f = {f["code"]: f for f in slow}["recovery_trend"]
    assert slow_f["title"] == "休息時心率降得比過去慢，超出誤差範圍"
    assert slow_f["severity"] == "dismiss" and slow_f["advice"] is None
    assert "±22.0%" in slow_f["detail"]
    assert {f["code"]: f for f in same}["recovery_trend"]["title"] == "休息時心率下降與過去的差距在誤差範圍內"
    jog = []
    _history_findings({"mean_work_pace_s_per_km": 250.0, "mean_rep_hr": 170, "mean_hr_drop": 5,
                       "recovery_jogging": True}, history, jog)
    assert "recovery_trend" not in {f["code"] for f in jog}


def _interval_summary(hr):
    return {"mean_work_pace_s_per_km": 250.0, "mean_rep_hr": hr, "rep_count": 6, "work_distance_m": 6000}


def _steady(hr, pace=250.0):
    return {"mean_work_pace_s_per_km": pace, "mean_rep_hr": hr, "steady_rep_hr": hr, "rep_count": 6,
            "work_distance_m": 6000}


def test_a_lower_steady_heart_rate_at_the_same_pace_is_marked_good():
    # 1 s over a 1000 m rep = 1 s/km; error = 1.645 x 1.4 % x sqrt(2) x 177 = 5.8 bpm
    history = [{"date": "2026-06-20", "signature": "6x1000m", "mean_pace_s_per_km": 250.5, "steady_rep_hr": 177},
               {"date": "2026-06-06", "signature": "6x1000m", "mean_pace_s_per_km": 253.0, "steady_rep_hr": 176}]
    summary = _steady(170)
    findings = []
    _history_findings(summary, history, findings)
    by = {f["code"]: f for f in findings}
    assert by["history"]["title"] == "配速相同、心率更低：朝好的方向"
    assert by["history"]["severity"] == "positive"
    assert [h["date"] for h in summary["history_trend"]] == ["2026-06-06", "2026-06-20", "今天"]


def test_faster_and_lower_is_good_slower_or_higher_is_not_judged():
    history = [{"date": "2026-06-20", "signature": "6x1000m", "mean_pace_s_per_km": 256.0, "steady_rep_hr": 177}]
    faster = []
    _history_findings(_steady(170), history, faster)
    assert {f["code"]: f for f in faster}["history"]["title"] == "配速更快、心率更低：朝好的方向"
    higher = []
    _history_findings(_steady(185, pace=256.0), history, higher)
    h = {f["code"]: f for f in higher}["history"]
    assert h["severity"] == "info" and "不能單獨當成疲勞的指標" in h["detail"]
    slower = []
    _history_findings(_steady(170, pace=262.0), history, slower)
    assert {f["code"]: f for f in slower}["history"]["severity"] == "info"


def test_a_heart_rate_gap_within_measurement_error_is_not_judged():
    history = [{"date": "2026-06-20", "signature": "6x1000m", "mean_pace_s_per_km": 250.5, "steady_rep_hr": 175}]
    findings = []
    _history_findings(_steady(170), history, findings)
    by = {f["code"]: f for f in findings}
    assert by["history"]["title"] == "與上次同課表比較" and by["history"]["severity"] == "info"


def test_steady_heart_rate_uses_only_reps_of_three_minutes_or_more():
    long_reps = _analyse([4.5] * 4)  # 1000 m in 222 s
    assert long_reps["summary"]["steady_rep_hr"] and long_reps["summary"]["steady_rep_count"] == 4
    short = _analyse([6.0] * 4)  # 1000 m in 167 s
    assert "steady_rep_hr" not in short["summary"]


def test_signature_labels():
    assert signature_label("6x1000m", "intervals") == "6 × 1000m"
    assert signature_label("3x(4x400m)", "intervals") == "3 組 × (4 × 400m)"
    assert signature_label("6x60s + 6x30s", "intervals") == "6 × 60 秒 + 6 × 30 秒"
    assert signature_label("tempo:6.2km", "tempo") == "6.2 公里節奏跑"
    assert signature_label("continuous", "easy") == "輕鬆跑"

"""Coach findings and the narrative's number check, on synthetic sessions."""

from __future__ import annotations

from datetime import date

from app.workout_analysis import analyse_workout, resolve_hr_profile
from app.workout_narrative import build_facts, offline_narrative, signature_label, unverified_numbers
from app.workout_segmentation import detect_workout
from tests.test_workout_segmentation import EASY, make_tele

DEVICE_HR = {"max_hr": 200, "resting_hr": 55, "hr_calc_type": "percent_hrr",
             "zone_high_bounds": [130, 140, 152, 175, 188, 200]}


def _hr():
    return resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=DEVICE_HR,
                              history_peak_30s=None, birth_year=None, on_date=date(2026, 7, 1))


def _session(rep_speeds, rest_s=120):
    plan = [("warmup", 720, EASY)]
    for i, sp in enumerate(rep_speeds):
        plan.append(("work", round(1000 / sp), sp))
        if i < len(rep_speeds) - 1:
            plan.append(("rest", rest_s, 0.0))
    plan.append(("cooldown", 480, EASY))
    tele = make_tele(plan, noise=0.02)
    det = detect_workout(tele, EASY)
    return tele, det


def _codes(analysis):
    return {f["code"]: f for f in analysis["findings"]}


def test_first_rep_too_fast_and_fade_are_found():
    tele, det = _session([4.75, 4.5, 4.48, 4.42, 4.38, 4.33])
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=None,
                        hr=_hr(), easy_speed=EASY)
    codes = _codes(a)
    assert "first_rep_fast" in codes
    assert "fade" in codes
    assert codes["fade"]["severity"] == "warning"
    assert [r["rep_number"] for r in a["reps"]] == [1, 2, 3, 4, 5, 6]


def test_even_pacing_is_praised_and_not_flagged():
    tele, det = _session([4.5] * 6)
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=None,
                        hr=_hr(), easy_speed=EASY)
    codes = _codes(a)
    assert codes["consistency"]["severity"] == "positive"
    assert "first_rep_fast" not in codes and "fade" not in codes


def test_rep_pace_uses_the_confirmed_nominal_distance():
    tele, det = _session([4.5] * 4)
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=None,
                        hr=_hr(), easy_speed=EASY)
    for r in a["reps"]:
        assert r["distance_m"] == 1000
        assert abs(r["pace_s_per_km"] - r["moving_s"]) < 1e-6


def test_target_pace_adherence():
    tele, det = _session([4.5] * 5)  # 222 s/km
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=240,
                        hr=_hr(), easy_speed=EASY)
    assert _codes(a)["target"]["title"] == "比課表要求快太多"


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


def test_offline_narrative_has_all_sections_and_only_known_numbers():
    tele, det = _session([4.75, 4.5, 4.48, 4.42, 4.38, 4.33])
    a = analyse_workout(tele, det["segments"], session_type="intervals", target_pace_s_per_km=None,
                        hr=_hr(), easy_speed=EASY)
    facts = build_facts(signature_label="6 × 1000m", session_type="intervals", activity_date="2026-07-01",
                        analysis=a, sub_sport="track")
    text = offline_narrative(facts)
    for heading in ("### 今日課表判讀", "### 表現總評", "### 配速控制", "### 下次訓練建議"):
        assert heading in text
    assert unverified_numbers(text, facts, rep_count=6) == []


def test_signature_labels():
    assert signature_label("6x1000m", "intervals") == "6 × 1000m"
    assert signature_label("3x(4x400m)", "intervals") == "3 組 × (4 × 400m)"
    assert signature_label("6x60s + 6x30s", "intervals") == "6 × 60 秒 + 6 × 30 秒"
    assert signature_label("tempo:6.2km", "tempo") == "6.2 公里節奏跑"
    assert signature_label("continuous", "easy") == "輕鬆跑"

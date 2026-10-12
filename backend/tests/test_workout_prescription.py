"""Prescription inference, rounding, alignment and the text-grounding check."""

from __future__ import annotations

from app.workout_prescription import (
    _check_against_text,
    _normalise_blocks,
    align,
    coach_round,
    describe,
    expand,
    fill_missing_targets,
    from_assignment,
    infer,
    looks_like_workout,
)


def _reps(lap_seconds, distance=400, rest=60):
    reps, rests = [], []
    idx = 1
    for k, t in enumerate(lap_seconds, 1):
        reps.append({"index": idx, "rep_number": k, "nominal_m": distance, "nominal_s": None,
                     "distance_m": distance, "pace_s_per_km": t / distance * 1000})
        idx += 1
        if k < len(lap_seconds):
            rests.append({"index": idx, "elapsed_s": rest})
            idx += 1
    return reps, rests


def test_coach_rounding():
    assert coach_round(222, lap=False) == 220
    assert coach_round(221.4, lap=False) == 220
    assert coach_round(223.1, lap=False) == 225
    assert coach_round(84.6, lap=True) == 85
    assert coach_round(83.2, lap=True) == 84
    assert coach_round(89.6, lap=True) == 90


def test_progression_90_85_80_is_found():
    laps = [90.4, 89.8, 90.6, 89.5, 90.1, 85.2, 84.6, 85.4, 85.0, 84.8, 80.3, 79.8, 80.6, 80.1, 79.6]
    reps, rests = _reps(laps)
    p = infer(reps, rests, "intervals")
    assert [b["reps"] for b in p["blocks"]] == [5, 5, 5]
    assert [round(b["targets_s_per_km"][0] * 0.4) for b in p["blocks"]] == [90, 85, 80]
    assert p["blocks"][0]["rest_s"] == 60


def test_a_fade_is_never_inferred_as_a_prescription():
    laps = [84.0, 84.3, 83.8, 84.1, 84.2, 87.5, 88.0, 88.4, 89.0, 89.5]
    reps, rests = _reps(laps)
    p = infer(reps, rests, "intervals")
    assert len(p["blocks"]) == 1


def test_mixed_distances_get_their_own_targets():
    reps = [{"index": 1, "rep_number": 1, "nominal_m": 2000, "nominal_s": None, "distance_m": 2000, "pace_s_per_km": 231},
            {"index": 3, "rep_number": 2, "nominal_m": 1000, "nominal_s": None, "distance_m": 1000, "pace_s_per_km": 219},
            {"index": 5, "rep_number": 3, "nominal_m": 800, "nominal_s": None, "distance_m": 800, "pace_s_per_km": 209}]
    rests = [{"index": 2, "elapsed_s": 120}, {"index": 4, "elapsed_s": 120}]
    p = infer(reps, rests, "intervals")
    assert [b["targets_s_per_km"][0] for b in p["blocks"]] == [230, 220, 210]


def test_expand_align_and_describe():
    p = {"source": "athlete_text", "blocks": [
        {"reps": 2, "distance_m": 400, "duration_s": None, "targets_s_per_km": [225.0], "rest_s": 60},
        {"reps": 1, "distance_m": 1000, "duration_s": None, "targets_s_per_km": [220.0], "rest_s": None}]}
    wanted = expand(p)
    assert [w["target_label"] for w in wanted] == ["90 秒", "90 秒", "3:40/km"]
    reps, _ = _reps([89, 90])
    reps.append({"rep_number": 3, "nominal_m": 1000})
    assert align(p, reps)["issues"] == []
    reps[2]["nominal_m"] = 800
    assert align(p, reps)["issues"] == ["第 3 趟要求 1000m，實際判讀為 800m"]
    assert describe(p) == "2 × 400m @ 90 秒，休 60 秒 ＋ 1000m @ 3:40/km"


def test_missing_targets_are_filled_and_marked():
    real = {"source": "activity_name", "blocks": [
        {"reps": 5, "distance_m": 400, "duration_s": None, "targets_s_per_km": [], "rest_s": 60}]}
    reps, rests = _reps([84.2, 84.0, 83.9, 84.4, 84.1])
    filled = fill_missing_targets(real, infer(reps, rests, "intervals"))
    assert filled["blocks"][0]["targets_inferred"] is True
    assert round(filled["blocks"][0]["targets_s_per_km"][0] * 0.4) == 84


def test_parsed_numbers_must_come_from_the_text():
    ok = [{"reps": 5, "distance_m": 400, "duration_s": None, "rest_s": 60, "_raw_targets": [90.0]},
          {"reps": 5, "distance_m": 400, "duration_s": None, "rest_s": 60, "_raw_targets": [85.0]},
          {"reps": 5, "distance_m": 400, "duration_s": None, "rest_s": 60, "_raw_targets": [80.0]}]
    assert _check_against_text(ok, "400x15 90 85 80 間休60") == []
    invented = [{"reps": 10, "distance_m": 400, "duration_s": None, "rest_s": 90, "_raw_targets": [84.0]}]
    assert _check_against_text(invented, "400 x 10 84/圈") == ["rest_s 90"]
    ranged = [{"reps": 4, "distance_m": 1000, "duration_s": None, "rest_s": None,
               "_raw_targets": [250.0, 243.0, 237.0, 230.0]}]
    assert _check_against_text(ranged, "1000m x 4 配速4:10～3:50") == []
    km = [{"reps": 6, "distance_m": 1000, "duration_s": None, "rest_s": 120, "_raw_targets": []}]
    assert _check_against_text(km, "1km x 6 r'2min") == []


def test_a_coach_pace_range_is_a_tolerance():
    seg = {"kind": "interval", "distanceMeters": 1200, "repetitions": 4, "pace": "3:40 /km–3:45 /km",
           "restSeconds": 90}
    p = from_assignment([seg], "4 x 1200")
    block = p["blocks"][0]
    assert block["targets_s_per_km"] == [222.5] and block["tolerance_s_per_km"] == 2.5
    rep = expand(p)[0]
    assert rep["target_tolerance_s_per_km"] == 2.5 and rep["target_label"] == "3:40–3:45/km"
    single = from_assignment([{**seg, "pace": "3:45 /km"}], "4 x 1200")["blocks"][0]
    assert single["targets_s_per_km"] == [225.0] and single["tolerance_s_per_km"] is None


def test_a_plus_minus_tolerance_in_the_athletes_text():
    blocks, problems = _normalise_blocks([{"reps": 10, "distance_m": 400, "targets": [86], "tolerance": 1,
                                           "target_unit": "per_rep_s", "rest_s": 60}])
    assert problems == []
    assert blocks[0]["tolerance_s_per_km"] == 2.5  # 1 s over 400 m
    assert expand({"blocks": blocks})[0]["target_label"] == "85–87 秒"
    assert _check_against_text(blocks, "400 x 10 86±1 秒 組休60") == []
    assert _check_against_text(blocks, "400 x 10 86 秒 組休60") == ["容許範圍 1"]


def test_workout_names():
    assert looks_like_workout("400 x 10 組休1分鐘 84/圈")
    assert looks_like_workout("2000 1600 1200 800")
    assert not looks_like_workout("大安區 跑步")
    assert not looks_like_workout("放鬆跑10k")

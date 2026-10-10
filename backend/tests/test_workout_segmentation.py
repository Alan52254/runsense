"""Workout-structure detection on synthetic 1 Hz recordings.

Each recording is built from a plan of (role, seconds, speed m/s) pieces
with deterministic GPS-like noise, so every case is exact and repeatable.
The real-data validation (43 athlete-labelled Garmin sessions) is
described in app/workout_segmentation.py's module docstring.
"""

from __future__ import annotations

import random

from app.workout_segmentation import detect_workout, signature, snap_distance, snap_duration

EASY = 3.0  # m/s, ~5:33 /km


def make_tele(plan, *, sub_sport="track", pause_rests=False, manual_laps=True, noise=0.06, seed=7):
    rng = random.Random(seed)
    t_list, d_list, v_list, hr_list, cad_list = [], [], [], [], []
    laps, events = [], [[0.0, "start"]]
    t = 0
    d = 0.0
    hr = 100.0
    for role, seconds, speed in plan:
        lap_start, lap_d0 = t, d
        paused = pause_rests and role == "rest"
        if paused:
            events.append([float(t), "stop_all"])
        for _ in range(seconds):
            v = max(0.0, speed * (1 + rng.uniform(-noise, noise))) if speed > 0 else 0.0
            target_hr = 95 + 22 * speed
            hr += (target_hr - hr) * 0.05
            if not paused:
                t_list.append(t)
                d_list.append(round(d, 1))
                v_list.append(round(v, 3))
                hr_list.append(round(hr))
                cad_list.append(round(150 + 8 * speed) if speed > 1 else None)
            d += v
            t += 1
        if paused:
            events.append([float(t), "start"])
        laps.append({"start_offset_s": float(lap_start), "elapsed_s": float(seconds), "timer_s": float(seconds),
                     "distance_m": round(d - lap_d0, 1), "avg_hr": None, "max_hr": None,
                     "trigger": "manual" if manual_laps else "distance", "intensity": "active",
                     "wkt_step": None})
    t_list.append(t)
    d_list.append(round(d, 1))
    v_list.append(0.0)
    hr_list.append(round(hr))
    cad_list.append(None)
    events.append([float(t), "stop_all"])
    return {"sport": "running", "sub_sport": sub_sport, "laps": laps, "timer_events": events,
            "workout_steps": [], "hr_profile": {},
            "samples": {"t": t_list, "d": d_list, "v": v_list, "hr": hr_list, "cad": cad_list}}


def intervals(reps, rep_m, rep_speed, rest_s, rest_speed, warm_s=600, cool_s=480):
    plan = [("warmup", warm_s, EASY)]
    for i in range(reps):
        plan.append(("work", round(rep_m / rep_speed), rep_speed))
        if i < reps - 1:
            plan.append(("rest", rest_s, rest_speed))
    plan.append(("cooldown", cool_s, EASY * 0.95))
    return plan


def works(result):
    return [s for s in result["segments"] if s["role"] == "work"]


def test_six_by_1000_with_standing_recovery():
    tele = make_tele(intervals(6, 1000, 4.5, 120, 0.0))
    r = detect_workout(tele, EASY)
    assert r["kind"] == "intervals"
    assert r["signature"] == "6x1000m"
    assert [s["nominal_m"] for s in works(r)] == [1000] * 6
    assert r["confidence"] >= 0.85


def test_ten_by_400_with_jog_recovery_and_400m_autolaps():
    # the athlete never presses lap: the watch auto-laps every 400 m, and
    # the recoveries are jogged -- structure must come from the effort
    tele = make_tele(intervals(10, 400, 5.2, 90, 2.4), manual_laps=False)
    r = detect_workout(tele, EASY)
    assert r["signature"] == "10x400m"
    rests = [s for s in r["segments"] if s["role"] == "rest"]
    assert len(rests) == 9


def test_float_recovery_still_separates_reps():
    # 4 x 1000 m at 3:38 /km with 90 s recoveries at ~4:20 /km
    tele = make_tele(intervals(4, 1000, 4.59, 90, 3.85))
    r = detect_workout(tele, EASY)
    assert r["signature"] == "4x1000m"


def test_rep_boundaries_follow_the_athletes_lap_presses():
    plan = intervals(5, 800, 4.8, 120, 0.0)
    tele = make_tele(plan)
    r = detect_workout(tele, EASY)
    lap_marks = {round(lap["start_offset_s"]) for lap in tele["laps"]}
    for s in works(r):
        assert s["start_s"] in lap_marks
        assert s["end_s"] in lap_marks


def test_pyramid_keeps_each_distance():
    plan = [("warmup", 600, EASY)]
    for i, m in enumerate([400, 800, 1200, 800, 400]):
        plan.append(("work", round(m / 4.7), 4.7))
        if i < 4:
            plan.append(("rest", 120, 0.0))
    plan.append(("cooldown", 400, EASY))
    r = detect_workout(make_tele(plan), EASY)
    assert r["signature"] == "400m-800m-1200m-800m-400m"


def test_sets_are_split_by_structural_long_rests():
    plan = [("warmup", 600, EASY)]
    for set_i in range(3):
        for rep in range(4):
            plan.append(("work", round(400 / 5.2), 5.2))
            if rep < 3:
                plan.append(("rest", 60, 0.0))
        if set_i < 2:
            plan.append(("rest", 300, 0.0))
    plan.append(("cooldown", 400, EASY))
    r = detect_workout(make_tele(plan), EASY)
    assert r["signature"] == "3x(4x400m)"
    assert sum(1 for s in r["segments"] if s["role"] == "set_rest") == 2


def test_short_stop_inside_a_rep_is_an_interruption_not_a_recovery():
    plan = [("warmup", 600, EASY)]
    for i in range(5):
        if i == 2:
            plan += [("work", 133, 4.5), ("rest", 25, 0.0), ("work", 89, 4.5)]  # 600 m + stop + 400 m
        else:
            plan.append(("work", 222, 4.5))
        if i < 4:
            plan.append(("rest", 180, 0.0))
    plan.append(("cooldown", 400, EASY))
    tele = make_tele(plan, pause_rests=False)
    r = detect_workout(tele, EASY)
    assert r["signature"] == "5x1000m"
    interrupted = [s for s in works(r) if s.get("interruptions")]
    assert len(interrupted) == 1


def test_time_based_reps():
    plan = [("warmup", 600, EASY)]
    speeds = [4.9, 4.6, 4.75, 4.5, 4.8, 4.65]
    for i, sp in enumerate(speeds):
        plan.append(("work", 60, sp))
        if i < 5:
            plan.append(("rest", 60, 1.2))
    plan.append(("cooldown", 400, EASY))
    r = detect_workout(make_tele(plan), EASY)
    assert r["signature"] == "6x60s"


def test_easy_run_with_traffic_light_stops_stays_continuous():
    plan = [("steady", 900, 3.05), ("stop", 40, 0.0), ("steady", 700, 3.0), ("stop", 35, 0.0),
            ("steady", 1100, 3.1)]
    r = detect_workout(make_tele(plan, sub_sport="generic", manual_laps=False), EASY)
    assert r["kind"] == "continuous"


def test_paused_recoveries_and_sparse_records():
    tele = make_tele(intervals(8, 400, 5.3, 75, 0.0), pause_rests=True)
    r = detect_workout(tele, EASY)
    assert r["signature"] == "8x400m"


def test_tempo_inside_easy_running():
    plan = [("warmup", 900, EASY), ("work", 1500, 4.2), ("cooldown", 600, EASY)]
    r = detect_workout(make_tele(plan, sub_sport="generic", manual_laps=False), EASY)
    assert r["kind"] == "tempo"


def test_insufficient_recording():
    tele = make_tele([("steady", 40, 3.0)])
    assert detect_workout(tele)["kind"] == "insufficient"


def test_snapping_helpers():
    assert snap_distance(1012, 0.05) == 1000
    assert snap_distance(1100, 0.05) is None
    assert snap_distance(412, 0.05) == 400
    assert snap_duration(61) == 60
    assert snap_duration(66) is None


def test_signature_formatting():
    segs = [{"role": "work", "start_s": 0, "end_s": 10, "nominal_m": 1000},
            {"role": "rest", "start_s": 10, "end_s": 20},
            {"role": "work", "start_s": 20, "end_s": 30, "nominal_m": 1000},
            {"role": "set_rest", "start_s": 30, "end_s": 40},
            {"role": "work", "start_s": 40, "end_s": 50, "nominal_m": 300}]
    assert signature(segs, "intervals") == "2x1000m + 300m"

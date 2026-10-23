"""Pace and segments for a ranked training-plan candidate, by rule (ADR 0002).

The Athlete's own easy pace anchors the bands when there is enough history;
otherwise the reviewed per-type default ranges stand in, and say so.
"""

from __future__ import annotations

from app.athlete_pace import candidate_pace


def test_an_easy_run_is_paced_from_the_athletes_own_easy_runs():
    plan = candidate_pace("EASY_RUN", 40, 7.0, easy_s_per_km=330)

    assert plan["pace_source"] == "athlete_history"
    assert plan["target_pace_range_s_per_km"] == [330, 350]
    assert plan["target_pace_s_per_km"] == 340
    assert [s["kind"] for s in plan["segments"]] == ["warmup", "work", "cooldown"]
    warmup, main, cooldown = plan["segments"]
    assert warmup["duration_seconds"] == 300
    assert warmup["target_pace_range_sec_per_km"] == [350, 375]
    assert main["duration_seconds"] == 1800
    assert main["distance_meters"] == 6000
    assert main["target_pace_range_sec_per_km"] == [330, 350]
    assert cooldown["duration_seconds"] == 300
    assert cooldown["target_pace_range_sec_per_km"] == [350, 375]


def test_without_enough_history_the_reviewed_default_ranges_stand_in_and_say_so():
    plan = candidate_pace("STEADY_RUN", 45, 9.0, easy_s_per_km=None)

    assert plan["pace_source"] == "rule_default"
    assert plan["target_pace_range_s_per_km"] == [320, 340]
    assert plan["target_pace_s_per_km"] == 330
    warmup, main, cooldown = plan["segments"]
    assert (warmup["duration_seconds"], main["duration_seconds"], cooldown["duration_seconds"]) == (600, 1800, 300)
    assert main["distance_meters"] == 7000
    assert warmup["target_pace_range_sec_per_km"] == [380, 400]
    assert cooldown["target_pace_range_sec_per_km"] == [380, 400]


# --------------------------------------------------------------------------
# GET /training-plan/today carries each candidate's pace (the wire shape)
# --------------------------------------------------------------------------

from datetime import date  # noqa: E402

from app.plan_scenario import AthleteFacts, evaluate_scenario, resolve_scenario  # noqa: E402
from app.training_plan_service import _serialise  # noqa: E402


def _evaluation():
    facts = AthleteFacts(local_date=date(2026, 10, 23), observation_days=28, acute_load=120.0,
                         chronic_load=1100.0, temperature_c=18.0, humidity_pct=60.0,
                         weather_state="CACHED", reported_body_part=None, reported_severity_band=None)
    return evaluate_scenario(resolve_scenario(facts, None))


def test_every_ranked_run_carries_server_pace_and_segments_and_rest_carries_none():
    wire = _serialise(_evaluation(), easy_s_per_km=330)
    by_id = {c["candidate_id"]: c for c in wire["candidates"]}

    assert by_id["easy-run"]["pace_source"] == "athlete_history"
    assert by_id["easy-run"]["target_pace_range_s_per_km"] == [330, 350]
    assert [s["kind"] for s in by_id["steady-run"]["segments"]] == ["warmup", "work", "cooldown"]
    rest = by_id["rest-day"]
    assert (rest["pace_source"], rest["target_pace_s_per_km"], rest["target_pace_range_s_per_km"], rest["segments"]) == (None, None, None, [])


def test_a_newcomer_without_easy_runs_gets_the_rule_default_pace():
    wire = _serialise(_evaluation(), easy_s_per_km=None)
    easy = next(c for c in wire["candidates"] if c["candidate_id"] == "easy-run")

    assert easy["pace_source"] == "rule_default"
    assert easy["target_pace_s_per_km"] == 370

"""Plan Scenario resolution and evaluation.

These tests are deliberately database-free: a Plan Scenario is resolved from
already-read facts, so plan behaviour can be pinned down without Postgres or
HTTP. Candidate generation and Plan Ranking are exercised through the seam,
never re-implemented here.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from app.plan_scenario import (
    AthleteFacts,
    ScenarioOverride,
    evaluate_scenario,
    resolve_scenario,
    urgency_from_severity_band,
)
from app.safety_triage import TriageUrgency
from app.training_plan_candidates import TrainingPlanContext, WorkoutType

_TODAY = date(2026, 8, 30)


def _facts(**overrides) -> AthleteFacts:
    base = dict(
        local_date=_TODAY,
        observation_days=20,
        acute_load=400.0,
        chronic_load=350.0,
        temperature_c=24.0,
        humidity_pct=60.0,
        weather_state="LIVE",
        reported_body_part=None,
        reported_severity_band=None,
    )
    base.update(overrides)
    return AthleteFacts(**base)


# --------------------------------------------------------------------------
# A Scenario Override carries facts only (ADR 0002 enforced by absence)
# --------------------------------------------------------------------------


def test_scenario_override_accepts_only_situational_facts():
    override = ScenarioOverride(
        local_date=date(2026, 11, 16),
        temperature_c=32.0,
        humidity_pct=85.0,
        available_minutes=30,
        reported_body_part="calf",
        reported_severity_band="MILD",
        label="Race day",
    )

    assert override.temperature_c == 32.0
    assert override.available_minutes == 30


@pytest.mark.parametrize(
    "prescription_field",
    ["distance_km", "duration_minutes", "pace_seconds_per_km", "intensity", "workout_type"],
)
def test_scenario_override_has_no_field_for_a_prescription(prescription_field):
    """ADR 0002 is enforced by the field not existing, not by review."""
    with pytest.raises(TypeError):
        ScenarioOverride(**{prescription_field: 10})


def test_a_resolved_scenario_cannot_be_mutated_after_resolution():
    resolved = resolve_scenario(_facts(), ScenarioOverride())

    with pytest.raises(FrozenInstanceError):
        resolved.label = "tampered"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Today is the scenario with nothing overridden
# --------------------------------------------------------------------------


def test_an_empty_override_resolves_to_the_athletes_actual_facts():
    facts = _facts()

    resolved = resolve_scenario(facts, ScenarioOverride())

    assert resolved.is_today is True
    assert resolved.overridden_fields == ()
    assert resolved.facts == facts


def test_no_override_at_all_is_the_same_as_an_empty_one():
    facts = _facts()

    assert resolve_scenario(facts, None) == resolve_scenario(facts, ScenarioOverride())


def test_an_empty_override_reproduces_todays_plan_context_exactly():
    facts = _facts()

    context = resolve_scenario(facts, ScenarioOverride()).plan_context

    assert context == TrainingPlanContext(
        triage_urgency=None,
        observation_days=20,
        acute_load=400.0,
        chronic_load=350.0,
        temperature_c=24.0,
        weather_state="LIVE",
    )


def test_the_plan_context_is_the_unmodified_existing_type():
    """Candidate generation and ranking must not need to learn a new input."""
    context = resolve_scenario(_facts(), ScenarioOverride(temperature_c=32.0)).plan_context

    assert type(context) is TrainingPlanContext


# --------------------------------------------------------------------------
# Overridden facts are recorded so a plan can be explained back
# --------------------------------------------------------------------------


def test_overriding_a_fact_records_which_fact_was_overridden():
    resolved = resolve_scenario(_facts(), ScenarioOverride(temperature_c=32.0))

    assert resolved.is_today is False
    assert resolved.overridden_fields == ("temperature_c",)
    assert resolved.facts.temperature_c == 32.0
    assert resolved.facts.humidity_pct == 60.0


def test_overriding_several_facts_records_all_of_them_in_a_stable_order():
    resolved = resolve_scenario(
        _facts(),
        ScenarioOverride(temperature_c=32.0, humidity_pct=85.0, available_minutes=30),
    )

    assert resolved.overridden_fields == ("temperature_c", "humidity_pct", "available_minutes")


def test_overriding_a_fact_with_its_current_value_is_still_an_override():
    """The Athlete asked about 24 degrees; that it matches today is a coincidence."""
    resolved = resolve_scenario(_facts(temperature_c=24.0), ScenarioOverride(temperature_c=24.0))

    assert resolved.overridden_fields == ("temperature_c",)


def test_an_overridden_scenario_carries_a_label_the_athlete_can_recognise():
    resolved = resolve_scenario(
        _facts(), ScenarioOverride(temperature_c=32.0, label="Race day in Taipei")
    )

    assert resolved.label == "Race day in Taipei"


def test_overriding_the_date_moves_the_scenario_without_touching_other_facts():
    race_day = date(2026, 11, 16)

    resolved = resolve_scenario(_facts(), ScenarioOverride(local_date=race_day))

    assert resolved.facts.local_date == race_day
    assert resolved.facts.acute_load == 400.0


# --------------------------------------------------------------------------
# Safety: an override may never make the Athlete's situation look safer
# --------------------------------------------------------------------------


def test_severity_bands_map_to_urgency_deterministically():
    assert urgency_from_severity_band("SEVERE") is TriageUrgency.PROMPT_CLINICIAN
    assert urgency_from_severity_band("MODERATE") is TriageUrgency.SELF_CARE_NEXT_STEP
    assert urgency_from_severity_band("MILD") is TriageUrgency.SELF_CARE_NEXT_STEP
    assert urgency_from_severity_band(None) is None
    assert urgency_from_severity_band("NOT_A_BAND") is None


def test_an_override_can_raise_urgency_when_the_athlete_reports_something_worse():
    resolved = resolve_scenario(
        _facts(), ScenarioOverride(reported_body_part="shin", reported_severity_band="SEVERE")
    )

    assert resolved.triage_urgency is TriageUrgency.PROMPT_CLINICIAN


def test_an_override_can_never_lower_urgency_below_the_recorded_facts():
    """ADR 0001: nothing downstream of the rules may make running look safer."""
    resolved = resolve_scenario(
        _facts(reported_body_part="shin", reported_severity_band="SEVERE"),
        ScenarioOverride(reported_severity_band="MILD"),
    )

    assert resolved.triage_urgency is TriageUrgency.PROMPT_CLINICIAN


def test_triage_that_forbids_running_still_forbids_it_under_every_override():
    resolved = resolve_scenario(
        _facts(reported_severity_band="SEVERE"),
        ScenarioOverride(
            temperature_c=18.0,
            available_minutes=120,
            reported_severity_band="MILD",
            reported_body_part=None,
        ),
    )

    evaluation = evaluate_scenario(resolved)

    assert [c.workout_type for c in evaluation.ranked_candidates] == [
        WorkoutType.REST_AND_SEEK_CARE
    ]
    assert all(c.running_allowed is False for c in evaluation.ranked_candidates)


def test_message_derived_emergency_triage_survives_the_planning_seam():
    resolved = resolve_scenario(
        _facts(
            reported_body_part=None,
            reported_severity_band=None,
            triage_urgency=TriageUrgency.EMERGENCY,
        ),
        ScenarioOverride(available_minutes=120, reported_severity_band="MILD"),
    )

    evaluation = evaluate_scenario(resolved)

    assert resolved.triage_urgency is TriageUrgency.EMERGENCY
    assert all(candidate.running_allowed is False for candidate in evaluation.ranked_candidates)


# --------------------------------------------------------------------------
# Available minutes is a fact about the Athlete, not a prescription
# --------------------------------------------------------------------------


def test_available_minutes_removes_options_the_athlete_could_not_finish():
    resolved = resolve_scenario(_facts(), ScenarioOverride(available_minutes=25))

    evaluation = evaluate_scenario(resolved)

    assert all(c.duration_minutes <= 25 for c in evaluation.ranked_candidates)
    assert WorkoutType.STEADY_RUN not in {c.workout_type for c in evaluation.ranked_candidates}


def test_available_minutes_never_changes_a_candidates_duration():
    """A reviewed template is reordered and filtered, never rewritten."""
    unconstrained = evaluate_scenario(resolve_scenario(_facts(), ScenarioOverride()))
    constrained = evaluate_scenario(
        resolve_scenario(_facts(), ScenarioOverride(available_minutes=25))
    )

    by_id = {c.candidate_id: c for c in unconstrained.ranked_candidates}
    for candidate in constrained.ranked_candidates:
        assert candidate.duration_minutes == by_id[candidate.candidate_id].duration_minutes
        assert candidate.distance_km == by_id[candidate.candidate_id].distance_km


def test_an_impossible_time_budget_still_leaves_the_athlete_an_option():
    resolved = resolve_scenario(_facts(), ScenarioOverride(available_minutes=1))

    evaluation = evaluate_scenario(resolved)

    assert len(evaluation.ranked_candidates) >= 1
    assert evaluation.ranked_candidates[0].workout_type is WorkoutType.REST_DAY


def test_a_time_budget_does_not_override_a_triage_block():
    resolved = resolve_scenario(
        _facts(reported_severity_band="SEVERE"), ScenarioOverride(available_minutes=1)
    )

    evaluation = evaluate_scenario(resolved)

    assert [c.workout_type for c in evaluation.ranked_candidates] == [
        WorkoutType.REST_AND_SEEK_CARE
    ]


# --------------------------------------------------------------------------
# Evaluation carries enough to explain itself
# --------------------------------------------------------------------------


def test_an_evaluation_reports_the_resolved_facts_it_used():
    resolved = resolve_scenario(_facts(), ScenarioOverride(temperature_c=32.0))

    evaluation = evaluate_scenario(resolved)

    assert evaluation.scenario is resolved
    assert evaluation.scenario.facts.temperature_c == 32.0


def test_an_evaluation_reports_whether_ranking_could_personalise():
    resolved = resolve_scenario(
        _facts(observation_days=2, chronic_load=None, temperature_c=None,
               weather_state="UNAVAILABLE"),
        ScenarioOverride(),
    )

    evaluation = evaluate_scenario(resolved)

    assert evaluation.abstained is True
    assert evaluation.abstention_reason == "INSUFFICIENT_OBSERVATIONS"
    assert evaluation.ranker_version


def test_a_hotter_scenario_is_ranked_from_the_same_reviewed_candidate_set():
    cool = evaluate_scenario(resolve_scenario(_facts(), ScenarioOverride(temperature_c=12.0)))
    hot = evaluate_scenario(resolve_scenario(_facts(), ScenarioOverride(temperature_c=34.0)))

    assert {c.candidate_id for c in cool.ranked_candidates} == {
        c.candidate_id for c in hot.ranked_candidates
    }


# --------------------------------------------------------------------------
# Pacing comes from the same scenario the candidates did
# --------------------------------------------------------------------------


def _paceable(**overrides):
    base = dict(sex="male", climate_reference_c=26.0)
    base.update(overrides)
    return _facts(**base)


def test_pacing_and_candidates_come_from_one_evaluation():
    evaluation = evaluate_scenario(
        resolve_scenario(_paceable(), ScenarioOverride(temperature_c=32.0))
    )

    assert evaluation.speed_loss_pct is not None
    assert evaluation.ranked_candidates
    assert evaluation.scenario.facts.temperature_c == 32.0


def test_a_hotter_scenario_costs_more_speed_than_a_cooler_one():
    cool = evaluate_scenario(resolve_scenario(_paceable(), ScenarioOverride(temperature_c=18.0)))
    hot = evaluate_scenario(resolve_scenario(_paceable(), ScenarioOverride(temperature_c=32.0)))

    assert hot.speed_loss_pct > cool.speed_loss_pct


def test_a_scenario_cooler_than_typical_is_allowed_to_be_a_bonus():
    evaluation = evaluate_scenario(
        resolve_scenario(_paceable(climate_reference_c=28.0), ScenarioOverride(temperature_c=14.0))
    )

    assert evaluation.speed_loss_pct < 0


def test_no_temperature_means_no_pacing_figure_rather_than_a_guess():
    evaluation = evaluate_scenario(
        resolve_scenario(_paceable(temperature_c=None), ScenarioOverride())
    )

    assert evaluation.speed_loss_pct is None
    assert evaluation.pacing_is_extrapolated is False


def test_no_typical_reference_means_no_pacing_figure():
    evaluation = evaluate_scenario(
        resolve_scenario(_paceable(climate_reference_c=None), ScenarioOverride(temperature_c=32.0))
    )

    assert evaluation.speed_loss_pct is None


def test_a_scenario_inside_the_measured_band_is_not_flagged_as_extrapolated():
    evaluation = evaluate_scenario(
        resolve_scenario(_paceable(), ScenarioOverride(temperature_c=20.0))
    )

    assert evaluation.pacing_is_extrapolated is False


def test_a_scenario_beyond_the_measured_band_is_flagged_rather_than_hidden():
    evaluation = evaluate_scenario(
        resolve_scenario(_paceable(), ScenarioOverride(temperature_c=38.0))
    )

    assert evaluation.speed_loss_pct is not None
    assert evaluation.pacing_is_extrapolated is True


def test_todays_pacing_is_unchanged_by_the_scenario_seam():
    facts = _paceable(temperature_c=30.0)
    from app.weather_pace import speed_loss_pct_relative_to_normal

    evaluation = evaluate_scenario(resolve_scenario(facts, ScenarioOverride()))

    assert evaluation.speed_loss_pct == round(
        speed_loss_pct_relative_to_normal(30.0, 26.0, "male"), 2
    )


# --------------------------------------------------------------------------
# Overrides compose without ever loosening the safety floor
# --------------------------------------------------------------------------


def test_two_overrides_compose_with_the_later_one_winning():
    accepted = ScenarioOverride(available_minutes=30, label="Short session")
    asked = ScenarioOverride(temperature_c=32.0)

    combined = accepted.merged_with(asked)

    assert combined.available_minutes == 30
    assert combined.temperature_c == 32.0
    assert combined.label == "Short session"


def test_a_later_override_replaces_the_same_fact():
    combined = ScenarioOverride(available_minutes=30).merged_with(
        ScenarioOverride(available_minutes=60)
    )

    assert combined.available_minutes == 60


def test_composing_overrides_cannot_lower_urgency_below_the_record():
    """An accepted proposal is still an override, and ADR 0001 still holds."""
    facts = _facts(reported_body_part="shin", reported_severity_band="SEVERE")
    accepted = ScenarioOverride(reported_severity_band="MILD")

    resolved = resolve_scenario(facts, accepted.merged_with(ScenarioOverride(temperature_c=18.0)))

    assert resolved.triage_urgency is TriageUrgency.PROMPT_CLINICIAN


def test_an_accepted_override_never_reopens_running_a_triage_blocked():
    facts = _facts(reported_severity_band="SEVERE")
    accepted = ScenarioOverride(reported_severity_band="MILD", available_minutes=90)

    evaluation = evaluate_scenario(resolve_scenario(facts, accepted))

    assert [c.workout_type for c in evaluation.ranked_candidates] == [
        WorkoutType.REST_AND_SEEK_CARE
    ]


def test_the_extrapolation_flag_follows_the_athletes_own_curve():
    """The men's and women's measured spans are about six degrees apart."""
    warm = ScenarioOverride(temperature_c=28.0)

    male = evaluate_scenario(resolve_scenario(_paceable(sex="male"), warm))
    female = evaluate_scenario(resolve_scenario(_paceable(sex="female"), warm))

    assert male.pacing_is_extrapolated is True
    assert female.pacing_is_extrapolated is False


def test_an_unset_profile_only_calls_measured_what_both_curves_measured():
    unset = evaluate_scenario(
        resolve_scenario(_paceable(sex=None), ScenarioOverride(temperature_c=28.0))
    )

    assert unset.pacing_is_extrapolated is True

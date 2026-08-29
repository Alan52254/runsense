from app.safety_triage import TriageUrgency
from app.training_plan_candidates import (
    TrainingPlanContext,
    WorkoutType,
    generate_training_plan_candidates,
)


def _ctx(**overrides):
    base = dict(
        triage_urgency=None,
        observation_days=20,
        acute_load=400.0,
        chronic_load=350.0,
        temperature_c=24.0,
        weather_state="LIVE",
    )
    base.update(overrides)
    return TrainingPlanContext(**base)


def test_prompt_clinician_triage_blocks_every_running_candidate():
    candidates = generate_training_plan_candidates(
        _ctx(triage_urgency=TriageUrgency.PROMPT_CLINICIAN)
    )

    assert len(candidates) == 1
    assert candidates[0].workout_type is WorkoutType.REST_AND_SEEK_CARE
    assert candidates[0].duration_minutes == 0
    assert candidates[0].distance_km == 0
    assert candidates[0].running_allowed is False
    assert candidates[0].provenance_rule_ids == ("TRIAGE_BLOCKS_RUNNING",)


def test_self_care_triage_offers_only_rest_or_an_easy_recovery_jog():
    candidates = generate_training_plan_candidates(
        _ctx(triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP)
    )
    types = [c.workout_type for c in candidates]

    assert types == [WorkoutType.REST_DAY, WorkoutType.RECOVERY_RUN]
    assert all(c.running_allowed for c in candidates)


def test_no_triage_offers_the_full_rest_to_steady_ladder():
    candidates = generate_training_plan_candidates(_ctx())
    types = [c.workout_type for c in candidates]

    assert types == [
        WorkoutType.REST_DAY,
        WorkoutType.RECOVERY_RUN,
        WorkoutType.EASY_RUN,
        WorkoutType.STEADY_RUN,
    ]
    # Candidates are frozen templates -- a ranker may reorder but never mutate.
    assert [c.intensity_ordinal for c in candidates] == [0, 1, 2, 3]

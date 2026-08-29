from app.safety_triage import TriageUrgency
from app.training_plan_candidates import (
    TrainingPlanContext,
    WorkoutType,
    generate_training_plan_candidates,
)


def test_prompt_clinician_triage_blocks_every_running_candidate():
    candidates = generate_training_plan_candidates(
        TrainingPlanContext(
            triage_urgency=TriageUrgency.PROMPT_CLINICIAN,
            observation_days=20,
            acute_load=400.0,
            chronic_load=350.0,
            temperature_c=24.0,
            weather_state="LIVE",
        )
    )

    assert len(candidates) == 1
    assert candidates[0].workout_type is WorkoutType.REST_AND_SEEK_CARE
    assert candidates[0].duration_minutes == 0
    assert candidates[0].distance_km == 0
    assert candidates[0].running_allowed is False
    assert candidates[0].provenance_rule_ids == ("TRIAGE_BLOCKS_RUNNING",)

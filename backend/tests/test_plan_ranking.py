from app.plan_ranking import DeterministicPlanRanker
from app.safety_triage import TriageUrgency
from app.training_plan_candidates import (
    TrainingPlanContext,
    generate_training_plan_candidates,
)


def test_cold_start_abstains_instead_of_claiming_model_confidence():
    context = TrainingPlanContext(
        triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
        observation_days=3,
        acute_load=120.0,
        chronic_load=None,
        temperature_c=None,
        weather_state="UNAVAILABLE",
    )
    candidates = generate_training_plan_candidates(context)

    result = DeterministicPlanRanker().rank(context, candidates)

    assert result.ranked_candidates == candidates
    assert result.ranker_version == "deterministic-plan-ranker-v1"
    assert result.abstained is True
    assert result.abstention_reason == "INSUFFICIENT_OBSERVATIONS"
    assert result.confidence is None
    assert result.feature_coverage == {
        "training_load": False,
        "weather": False,
        "injury_triage": True,
    }

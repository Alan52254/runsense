from app.plan_ranking import DeterministicPlanRanker, MLPlanRanker
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
        acute_load=350.0,
        chronic_load=350.0,
        temperature_c=20.0,
        weather_state="LIVE",
    )
    base.update(overrides)
    return TrainingPlanContext(**base)


def _rank(ctx):
    return DeterministicPlanRanker().rank(ctx, generate_training_plan_candidates(ctx))


def test_cold_start_abstains_instead_of_claiming_model_confidence():
    context = _ctx(observation_days=3, chronic_load=None, temperature_c=None,
                   weather_state="UNAVAILABLE",
                   triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP)

    result = _rank(context)

    assert result.ranker_version == "deterministic-plan-ranker-v2"
    assert result.abstained is True
    assert result.abstention_reason == "INSUFFICIENT_OBSERVATIONS"
    assert result.confidence is None
    assert result.reason_code == "COLD_START_ABSTAIN"
    # Gentlest first when we can't score.
    assert [c.intensity_ordinal for c in result.ranked_candidates] == sorted(
        c.intensity_ordinal for c in result.ranked_candidates
    )
    assert result.feature_coverage == {
        "training_load": False,
        "weather": False,
        "injury_triage": True,
    }


def test_elevated_load_ranks_recovery_above_steady_with_a_confidence():
    result = _rank(_ctx(acute_load=520.0, chronic_load=350.0))  # ratio ~1.49

    assert result.abstained is False
    assert result.reason_code == "LOAD_ELEVATED_FAVOR_RECOVERY"
    top = result.ranked_candidates[0]
    assert top.workout_type in {WorkoutType.REST_DAY, WorkoutType.RECOVERY_RUN}
    intensities = [c.intensity_ordinal for c in result.ranked_candidates]
    assert intensities == sorted(intensities)  # gentler-first under high load
    assert 0.0 < result.confidence <= 1.0
    assert result.candidate_scores[0].rationale  # non-empty explanation


def test_reduced_load_pushes_a_stimulus_up_the_order():
    result = _rank(_ctx(acute_load=210.0, chronic_load=350.0))  # ratio ~0.6

    assert result.reason_code == "LOAD_REDUCED_ADD_STIMULUS"
    top = result.ranked_candidates[0]
    assert top.workout_type in {WorkoutType.EASY_RUN, WorkoutType.STEADY_RUN}


def test_hot_weather_demotes_the_hardest_option():
    cool = _rank(_ctx(acute_load=210.0, chronic_load=350.0, temperature_c=18.0))
    hot = _rank(_ctx(acute_load=210.0, chronic_load=350.0, temperature_c=33.0))

    steady = "steady-run"
    cool_pos = [c.candidate_id for c in cool.ranked_candidates].index(steady)
    hot_pos = [c.candidate_id for c in hot.ranked_candidates].index(steady)
    assert hot_pos >= cool_pos
    hot_steady_score = next(s.score for s in hot.candidate_scores if s.candidate_id == steady)
    cool_steady_score = next(s.score for s in cool.candidate_scores if s.candidate_id == steady)
    assert hot_steady_score < cool_steady_score


def test_triage_forced_single_candidate_is_certain_not_abstained():
    result = _rank(_ctx(triage_urgency=TriageUrgency.PROMPT_CLINICIAN))

    assert len(result.ranked_candidates) == 1
    assert result.abstained is False
    assert result.confidence == 1.0
    assert result.reason_code == "TRIAGE_BLOCKED"


def test_ranking_is_always_a_permutation_of_the_supplied_candidates():
    ctx = _ctx(acute_load=400.0, chronic_load=350.0)
    candidates = generate_training_plan_candidates(ctx)
    result = DeterministicPlanRanker().rank(ctx, candidates)

    assert sorted(c.candidate_id for c in result.ranked_candidates) == sorted(
        c.candidate_id for c in candidates
    )
    assert len(result.candidate_scores) == len(candidates)


def test_experimental_ml_falls_back_when_weather_or_load_is_not_backed():
    context = _ctx(
        observation_days=20,
        acute_load=2300.0,
        chronic_load=2156.25,
        temperature_c=None,
        weather_state="UNAVAILABLE",
        triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
    )

    result = MLPlanRanker().rank(context, generate_training_plan_candidates(context))

    assert result.ranker_version == "deterministic-plan-ranker-v2"
    assert result.feature_coverage["weather"] is False
    assert all("28" not in reason for score in result.candidate_scores for reason in score.rationale)

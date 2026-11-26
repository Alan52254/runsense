from datetime import date
import json
from pathlib import Path

from app.plan_ranking import DeterministicPlanRanker, MLPlanRanker, ShadowPlanRanker
from app.plan_scenario import AthleteFacts, resolve_scenario
from app.safety_triage import TriageUrgency
from app.training_plan_candidates import (
    TrainingPlanCandidate,
    TrainingPlanContext,
    WorkoutType,
    generate_training_plan_candidates,
)
from ml.abstention import AbstentionPolicy
from ml.feature_contract import FEATURE_INDEX, feature_names


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


def test_shadow_ranker_never_changes_the_user_facing_order(monkeypatch):
    context = _ctx(acute_load=210.0, chronic_load=350.0, temperature_c=31.0)
    candidates = generate_training_plan_candidates(context)
    primary = DeterministicPlanRanker().rank(context, candidates)

    shadow = ShadowPlanRanker().rank(context, candidates)

    assert [c.candidate_id for c in shadow.ranked_candidates] == [
        c.candidate_id for c in primary.ranked_candidates
    ]
    assert shadow.ranker_version == primary.ranker_version
    assert shadow.shadow_ranker_version is not None
    assert shadow.shadow_candidate_scores


def test_calibrated_ml_mode_is_promoted_default_with_rollback_switches(monkeypatch):
    from app.plan_ranking import configured_plan_ranker

    monkeypatch.delenv("PLAN_RANKER_MODE", raising=False)
    assert isinstance(configured_plan_ranker(), MLPlanRanker)

    monkeypatch.setenv("PLAN_RANKER_MODE", "shadow_ml")
    assert isinstance(configured_plan_ranker(), ShadowPlanRanker)

    monkeypatch.setenv("PLAN_RANKER_MODE", "deterministic")
    assert isinstance(configured_plan_ranker(), DeterministicPlanRanker)


def test_ml_ranker_zero_or_negative_chronic_load_abstains_without_assertion_error():
    for bad_chronic in (0.0, -10.0):
        ctx = _ctx(observation_days=20, acute_load=200.0, chronic_load=bad_chronic)
        cands = generate_training_plan_candidates(ctx)
        res = MLPlanRanker().rank(ctx, cands)
        assert res.abstained is True
        assert res.abstention_reason == "NO_CHRONIC_LOAD"
        assert res.confidence is None
        assert [c.intensity_ordinal for c in res.ranked_candidates] == sorted(
            c.intensity_ordinal for c in cands
        )


def test_ml_ranker_cold_start_abstains_with_insufficient_observations():
    ctx = _ctx(observation_days=5, acute_load=100.0, chronic_load=200.0)
    res = MLPlanRanker().rank(ctx, generate_training_plan_candidates(ctx))
    assert res.abstained is True
    assert res.abstention_reason == "INSUFFICIENT_OBSERVATIONS"
    assert res.confidence is None


def test_ml_ranker_does_not_clamp_observation_days_and_forwards_wellness_fields():
    captured: list[list[float]] = []

    class _SpyModel:
        def predict_proba(self, X):
            captured.extend(X.tolist() if hasattr(X, "tolist") else X)
            return [[0.2, 0.8] if i == 1 else [0.8, 0.2] for i in range(len(X))]

    ranker = MLPlanRanker(policy=AbstentionPolicy(model_locked=True, min_confidence=0.34))
    ranker._xgb_model = _SpyModel()  # type: ignore[assignment]

    facts = AthleteFacts(
        local_date=date(2026, 8, 30),
        observation_days=10,
        acute_load=300.0,
        chronic_load=300.0,
        temperature_c=24.0,
        weather_state="LIVE",
        resting_hr_delta=4.5,
        sleep_hours=5.8,
        load_ramp_pct=18.2,
    )
    ctx = resolve_scenario(facts, None).plan_context
    assert ctx.resting_hr_delta == 4.5
    assert ctx.sleep_hours == 5.8
    assert ctx.load_ramp_pct == 18.2

    res = ranker.rank(ctx, generate_training_plan_candidates(ctx))
    assert res.abstained is False
    assert len(captured) == 4
    vec = captured[0]
    assert vec[FEATURE_INDEX["observation_days"]] == 10.0
    assert vec[FEATURE_INDEX["resting_hr_delta"]] == 4.5
    assert vec[FEATURE_INDEX["sleep_hours"]] == 5.8
    assert vec[FEATURE_INDEX["load_ramp_pct"]] == 18.2


def test_ml_ranker_triage_override_precedes_weather_and_model_gates():
    for urgency in (TriageUrgency.EMERGENCY, TriageUrgency.PROMPT_CLINICIAN):
        ctx = _ctx(
            triage_urgency=urgency,
            observation_days=30,
            acute_load=400.0,
            chronic_load=350.0,
            temperature_c=22.0,
            weather_state="LIVE",
        )
        cands = generate_training_plan_candidates(ctx)
        res = MLPlanRanker().rank(ctx, cands)
        assert res.abstained is True
        assert res.abstention_reason == "TRIAGE_OVERRIDE"
        assert res.confidence is None
        assert [c.workout_type for c in res.ranked_candidates] == [WorkoutType.REST_AND_SEEK_CARE]


def test_ml_ranker_single_non_triage_candidate_is_not_labeled_triage_override():
    ctx = _ctx(observation_days=20, acute_load=350.0, chronic_load=350.0)
    rest_only = (
        TrainingPlanCandidate("rest-day", WorkoutType.REST_DAY, 0, 0.0, True, ("CONSERVATIVE_REST_OPTION",)),
    )
    res = MLPlanRanker().rank(ctx, rest_only)
    assert res.abstained is False
    assert res.abstention_reason is None
    assert res.confidence == 1.0
    assert res.reason_code == "TIME_BUDGET_SINGLE_CANDIDATE"


def test_ml_ranker_low_confidence_abstains_to_deterministic_order():
    ctx = _ctx(observation_days=20, acute_load=350.0, chronic_load=350.0)
    cands = generate_training_plan_candidates(ctx)
    strict = MLPlanRanker(policy=AbstentionPolicy(model_locked=True, min_confidence=0.99))
    res = strict.rank(ctx, cands)
    assert res.abstained is True
    assert res.abstention_reason == "LOW_CONFIDENCE"
    assert res.confidence is None
    assert res.ranked_candidates == DeterministicPlanRanker().rank(ctx, cands).ranked_candidates


def test_ml_ranker_missing_or_corrupt_or_stale_23_feat_artifacts_fallback_cleanly(tmp_path: Path):
    ctx = _ctx(observation_days=20, acute_load=350.0, chronic_load=350.0)
    cands = generate_training_plan_candidates(ctx)

    # Empty dir -> deterministic fallback
    empty_res = MLPlanRanker(model_dir=tmp_path).rank(ctx, cands)
    assert empty_res.ranker_version == "deterministic-plan-ranker-v2"

    # Corrupt artifacts -> deterministic fallback
    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "xgb_plan_ranker.json").write_text("{not valid json", encoding="utf-8")
    (corrupt_dir / "plan_model_weights.json").write_text("{corrupt", encoding="utf-8")
    corrupt_res = MLPlanRanker(model_dir=corrupt_dir).rank(ctx, cands)
    assert corrupt_res.ranker_version == "deterministic-plan-ranker-v2"

    # Stale 23-feature weights without xgb -> discarded without misalignment, deterministic fallback
    stale_dir = tmp_path / "stale23"
    stale_dir.mkdir()
    stale_payload = {
        "feature_names": list(feature_names()[:23]),
        "linear_weights": [0.1] * 23,
        "linear_means": [0.0] * 23,
        "linear_stds": [1.0] * 23,
        "linear_bias": 0.0,
    }
    (stale_dir / "plan_model_weights.json").write_text(json.dumps(stale_payload), encoding="utf-8")
    stale_ranker = MLPlanRanker(model_dir=stale_dir)
    assert stale_ranker._linear_weights is None
    assert stale_ranker.rank(ctx, cands).ranker_version == "deterministic-plan-ranker-v2"


def test_ml_ranker_applies_platt_calibration_deterministically(tmp_path: Path):
    names = list(feature_names())
    weights_payload = {
        "feature_names": names,
        "linear_weights": [0.0] * 14 + [1.0] + [0.0] * (len(names) - 15),
        "linear_means": [0.0] * len(names),
        "linear_stds": [1.0] * len(names),
        "linear_bias": 0.0,
        "calibration": {
            "logistic_regression": {
                "calibrator_type": "PlattCalibrator",
                "a": 4.0,
                "b": -0.5,
                "fitted": True,
                "mode": "top_choice",
            }
        },
        "abstention_policy": {
            "min_observation_days": 7,
            "require_chronic_load": True,
            "min_confidence": 0.34,
            "model_locked": True,
        },
    }
    (tmp_path / "plan_model_weights.json").write_text(json.dumps(weights_payload), encoding="utf-8")
    ranker = MLPlanRanker(model_dir=tmp_path)
    ctx = _ctx(observation_days=20, acute_load=350.0, chronic_load=350.0)
    cands = generate_training_plan_candidates(ctx)
    res1 = ranker.rank(ctx, cands)
    res2 = ranker.rank(ctx, cands)
    assert res1 == res2
    assert res1.abstained is False
    assert res1.confidence is not None and 0.34 <= res1.confidence <= 1.0


def test_ml_ranker_is_pure_permutation_of_supplied_candidates():
    ctx = _ctx(observation_days=20, acute_load=350.0, chronic_load=350.0)
    cands = generate_training_plan_candidates(ctx)
    res = MLPlanRanker().rank(ctx, cands)
    assert sorted(c.candidate_id for c in res.ranked_candidates) == sorted(c.candidate_id for c in cands)
    by_id = {c.candidate_id: c for c in cands}
    for ranked_c in res.ranked_candidates:
        orig = by_id[ranked_c.candidate_id]
        assert ranked_c.duration_minutes == orig.duration_minutes
        assert ranked_c.distance_km == orig.distance_km
        assert ranked_c.workout_type == orig.workout_type

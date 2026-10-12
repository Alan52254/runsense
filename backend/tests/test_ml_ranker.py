"""OfflinePlanRanker.rank invariants and the leakage-safe benchmark harness."""

from __future__ import annotations

import pytest

from ml.abstention import AbstentionPolicy, AbstentionReason
from ml.calibration import IdentityCalibrator
from ml.feature_contract import feature_names, vectorize
from ml.logistic_regression import LogisticRegressionBaseline
from ml.ranker import (
    GUARDRAIL_NOTE,
    OfflinePlanRanker,
    RankableCandidate,
    RankingInvariantError,
    deterministic_order,
    evaluate,
)
from ml.synthetic import SyntheticConfig, generate_synthetic_observations


def _ctx(**over):
    base = {
        "chronic_load": 400.0,
        "observation_days": 30.0,
        "acute_chronic_ratio": 1.0,
        "weather_actionable": 1.0,
        "triage_escalated": 0.0,
    }
    base.update(over)
    return base


def _candidates(ctx):
    specs = [("rest", 0, 0.0, 0.0), ("recovery", 1, 3.0, 22.0), ("easy", 2, 7.0, 40.0)]
    out = []
    for cid, intensity, dist, dur in specs:
        feats = dict(ctx)
        feats.update(
            candidate_intensity_ord=float(intensity),
            candidate_distance_km=dist,
            candidate_duration_min=dur,
        )
        out.append(RankableCandidate(cid, feats))
    return out


def test_no_model_abstains_to_deterministic_order():
    cands = _candidates(_ctx())
    outcome = OfflinePlanRanker().rank(cands)
    assert outcome.abstained is True
    assert outcome.abstention_reason == AbstentionReason.MODEL_NOT_LOCKED.value
    assert outcome.calibrated_confidence is None
    assert outcome.used_deterministic_fallback is True
    assert outcome.ranked_candidate_ids == deterministic_order(cands)
    assert outcome.model_version


def test_ranking_is_always_a_permutation_of_inputs():
    cands = _candidates(_ctx())
    X = [vectorize(c.features) for c in cands]
    y = [1 if c.candidate_id == "recovery" else 0 for c in cands] * 1
    # Trivial fitted model + identity calibrator, locked policy.
    model = LogisticRegressionBaseline(epochs=50).fit(X + X, y + y)
    ranker = OfflinePlanRanker(
        model=model,
        calibrator=IdentityCalibrator(),
        policy=AbstentionPolicy(model_locked=True, min_confidence=0.0),
    )
    outcome = ranker.rank(cands)
    assert sorted(outcome.ranked_candidate_ids) == sorted(c.candidate_id for c in cands)
    assert len(outcome.ranked_candidate_ids) == len(cands)


def test_triage_escalation_forces_abstention_even_with_model():
    cands = _candidates(_ctx(triage_escalated=1.0))
    X = [vectorize(c.features) for c in cands]
    model = LogisticRegressionBaseline(epochs=50).fit(X + X, [0, 1, 0, 0, 1, 0])
    ranker = OfflinePlanRanker(
        model=model, calibrator=IdentityCalibrator(),
        policy=AbstentionPolicy(model_locked=True, min_confidence=0.0),
    )
    outcome = ranker.rank(cands)
    assert outcome.abstained is True
    assert outcome.abstention_reason == AbstentionReason.TRIAGE_OVERRIDE.value
    assert outcome.ranked_candidate_ids == deterministic_order(cands)


def test_cold_start_context_abstains_with_insufficient_observations():
    cands = _candidates(_ctx(observation_days=3.0))
    X = [vectorize(c.features) for c in cands]
    model = LogisticRegressionBaseline(epochs=50).fit(X + X, [0, 1, 0, 0, 1, 0])
    ranker = OfflinePlanRanker(
        model=model, calibrator=IdentityCalibrator(),
        policy=AbstentionPolicy(model_locked=True, min_confidence=0.0),
    )
    outcome = ranker.rank(cands)
    assert outcome.abstention_reason == AbstentionReason.INSUFFICIENT_OBSERVATIONS.value


def test_rank_rejects_empty():
    with pytest.raises(ValueError):
        OfflinePlanRanker().rank([])


def test_deterministic_order_is_gentlest_first():
    cands = _candidates(_ctx())
    assert deterministic_order(cands) == ("rest", "recovery", "easy")


def test_evaluate_runs_end_to_end_and_declares_no_winner():
    rows = generate_synthetic_observations(SyntheticConfig(seed=0))
    report = evaluate(rows, n_splits=4, gap=2, epochs=150)
    assert report.winner_declared is False
    assert report.production_ranker == "deterministic"
    assert report.note == GUARDRAIL_NOTE
    assert report.feature_names == feature_names()
    assert report.per_fold
    for fold in report.per_fold:
        if "skipped" in fold:
            continue
        block = fold["baseline"]
        assert 0.0 <= block["ece"] <= 1.0
        assert 0.0 <= block["top_choice_utility"] <= 1.0
        assert 0.0 <= block["abstention_coverage"] <= 1.0
        assert "subgroup_regime" in block
    assert "top_choice_utility" in report.baseline_aggregate
    d = report.as_dict()
    assert d["winner_declared"] is False


def test_evaluate_without_tree_adapter_marks_it_not_requested():
    rows = generate_synthetic_observations(SyntheticConfig(seed=1))
    report = evaluate(rows, n_splits=3, gap=1, epochs=120)
    assert report.tree_aggregate == {"status": "not requested"}


def test_evaluate_beats_random_on_synthetic_signal():
    rows = generate_synthetic_observations(SyntheticConfig(seed=0))
    report = evaluate(rows, n_splits=4, gap=2, epochs=300)
    # 3 candidates per decision -> chance top-1 is ~1/3. The baseline should
    # clear that on data with real latent structure.
    assert report.baseline_aggregate["top_choice_utility"] > 0.34

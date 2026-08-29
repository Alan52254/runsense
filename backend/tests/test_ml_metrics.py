"""Ranking-utility and abstention metrics."""

from __future__ import annotations

from ml.metrics import (
    QueryPrediction,
    abstention_coverage,
    mean_reciprocal_rank,
    risk_coverage_curve,
    selective_top_choice_utility,
    subgroup_report,
    top_choice_utility,
)


def _p(qid, ranked, truth, **kw):
    return QueryPrediction(qid, tuple(ranked), truth, **kw)


def test_top_choice_utility_counts_rank_one_hits():
    preds = [
        _p(1, ["a", "b", "c"], "a"),
        _p(2, ["b", "a", "c"], "a"),
        _p(3, ["c", "a", "b"], "c"),
    ]
    assert top_choice_utility(preds) == 2 / 3


def test_mrr_uses_reciprocal_rank_of_truth():
    preds = [_p(1, ["a", "b"], "b"), _p(2, ["a", "b"], "a")]
    assert mean_reciprocal_rank(preds) == (0.5 + 1.0) / 2


def test_abstained_predictions_are_excluded_from_utility():
    preds = [
        _p(1, ["a", "b"], "a"),
        _p(2, ["b", "a"], "a", abstained=True),
    ]
    assert top_choice_utility(preds) == 1.0
    assert abstention_coverage(preds) == 0.5
    assert selective_top_choice_utility(preds) == 1.0


def test_subgroup_report_splits_by_key():
    preds = [
        _p(1, ["a", "b"], "a", subgroups={"regime": "cold_start"}),
        _p(2, ["b", "a"], "a", subgroups={"regime": "cold_start"}),
        _p(3, ["a", "b"], "a", subgroups={"regime": "established"}),
    ]
    rep = subgroup_report(preds, "regime")
    assert set(rep) == {"cold_start", "established"}
    assert rep["cold_start"]["n"] == 2.0
    assert rep["cold_start"]["metric"] == 0.5
    assert rep["established"]["metric"] == 1.0


def test_risk_coverage_curve_orders_by_confidence():
    preds = [
        _p(1, ["a", "b"], "a", confidence=0.9),
        _p(2, ["b", "a"], "a", confidence=0.8),
        _p(3, ["a", "b"], "a", confidence=0.6),
    ]
    curve = risk_coverage_curve(preds)
    coverages = [c for c, _ in curve]
    assert coverages == sorted(coverages)
    assert curve[0][1] == 0.0  # most confident answer is correct -> 0 error


def test_empty_inputs_are_safe():
    assert top_choice_utility([]) == 0.0
    assert abstention_coverage([]) == 0.0
    assert risk_coverage_curve([]) == []

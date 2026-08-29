"""Abstention policy reasons."""

from __future__ import annotations

from ml.abstention import (
    BENCHMARK_POLICY,
    PRODUCTION_POLICY,
    AbstentionPolicy,
    AbstentionReason,
)


def test_production_policy_always_abstains_model_not_locked():
    d = PRODUCTION_POLICY.decide(
        observation_days=100, chronic_load=400.0, triage_escalated=False, top_confidence=0.99
    )
    assert d.abstain is True
    assert d.reason is AbstentionReason.MODEL_NOT_LOCKED


def test_triage_override_wins_over_everything():
    d = PRODUCTION_POLICY.decide(
        observation_days=100, chronic_load=400.0, triage_escalated=True, top_confidence=0.99
    )
    assert d.reason is AbstentionReason.TRIAGE_OVERRIDE


def test_cold_start_insufficient_observations():
    d = BENCHMARK_POLICY.decide(
        observation_days=5, chronic_load=400.0, triage_escalated=False, top_confidence=0.99
    )
    assert d.abstain is True
    assert d.reason is AbstentionReason.INSUFFICIENT_OBSERVATIONS


def test_no_chronic_load_abstains():
    d = BENCHMARK_POLICY.decide(
        observation_days=30, chronic_load=0.0, triage_escalated=False, top_confidence=0.99
    )
    assert d.reason is AbstentionReason.NO_CHRONIC_LOAD

    d2 = BENCHMARK_POLICY.decide(
        observation_days=30, chronic_load=None, triage_escalated=False, top_confidence=0.99
    )
    assert d2.reason is AbstentionReason.NO_CHRONIC_LOAD


def test_low_confidence_abstains():
    d = BENCHMARK_POLICY.decide(
        observation_days=30, chronic_load=400.0, triage_escalated=False, top_confidence=0.51
    )
    assert d.reason is AbstentionReason.LOW_CONFIDENCE


def test_healthy_established_athlete_does_not_abstain():
    d = BENCHMARK_POLICY.decide(
        observation_days=30, chronic_load=400.0, triage_escalated=False, top_confidence=0.8
    )
    assert d.abstain is False
    assert d.reason is None


def test_custom_thresholds_respected():
    policy = AbstentionPolicy(min_observation_days=14, min_confidence=0.7, model_locked=True)
    assert policy.decide(
        observation_days=10, chronic_load=1.0, triage_escalated=False, top_confidence=0.9
    ).reason is AbstentionReason.INSUFFICIENT_OBSERVATIONS

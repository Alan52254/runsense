"""Abstention policy for Plan Ranking.

A learned ranker must be able to say "I don't know" and fall back to
deterministic ordering rather than being forced into a call. The reasons here
mirror the training-plan-ranking spec:

* fewer than seven usable observation days, or no chronic load -> cold start
* Safety Triage escalated -> the model never gets a vote
* calibrated top confidence below threshold -> low confidence
* the model has not cleared a locked benchmark -> not enabled at all
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AbstentionReason(StrEnum):
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
    NO_CHRONIC_LOAD = "NO_CHRONIC_LOAD"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TRIAGE_OVERRIDE = "TRIAGE_OVERRIDE"
    MODEL_NOT_LOCKED = "MODEL_NOT_LOCKED"


@dataclass(frozen=True)
class AbstentionDecision:
    abstain: bool
    reason: AbstentionReason | None

    def as_dict(self) -> dict[str, object]:
        return {"abstain": self.abstain, "reason": self.reason.value if self.reason else None}


@dataclass(frozen=True)
class AbstentionPolicy:
    """Thresholds for deferring to deterministic ordering.

    ``model_locked`` defaults to ``False`` so the *production-shaped* policy
    always abstains -- production Plan Ranking stays deterministic until a
    locked benchmark exists. Benchmark code flips it to ``True`` to exercise
    the other reasons.
    """

    min_observation_days: int = 7
    require_chronic_load: bool = True
    min_confidence: float = 0.55
    model_locked: bool = False

    def decide(
        self,
        *,
        observation_days: float,
        chronic_load: float | None,
        triage_escalated: bool,
        top_confidence: float | None,
    ) -> AbstentionDecision:
        if triage_escalated:
            return AbstentionDecision(True, AbstentionReason.TRIAGE_OVERRIDE)
        if not self.model_locked:
            return AbstentionDecision(True, AbstentionReason.MODEL_NOT_LOCKED)
        if observation_days < self.min_observation_days:
            return AbstentionDecision(True, AbstentionReason.INSUFFICIENT_OBSERVATIONS)
        if self.require_chronic_load and (chronic_load is None or chronic_load <= 0.0):
            return AbstentionDecision(True, AbstentionReason.NO_CHRONIC_LOAD)
        if top_confidence is None or top_confidence < self.min_confidence:
            return AbstentionDecision(True, AbstentionReason.LOW_CONFIDENCE)
        return AbstentionDecision(False, None)


PRODUCTION_POLICY = AbstentionPolicy()
BENCHMARK_POLICY = AbstentionPolicy(model_locked=True)

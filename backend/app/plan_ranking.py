"""Plan-ranking adapters that cannot invent or alter workout candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from app.training_plan_candidates import TrainingPlanCandidate, TrainingPlanContext


@dataclass(frozen=True)
class PlanRankingResult:
    ranked_candidates: tuple[TrainingPlanCandidate, ...]
    ranker_version: str
    abstained: bool
    abstention_reason: str | None
    confidence: float | None
    feature_coverage: Mapping[str, bool]


class PlanRanker(Protocol):
    def rank(
        self,
        context: TrainingPlanContext,
        candidates: Sequence[TrainingPlanCandidate],
    ) -> PlanRankingResult: ...


class DeterministicPlanRanker:
    version = "deterministic-plan-ranker-v1"

    def rank(
        self,
        context: TrainingPlanContext,
        candidates: Sequence[TrainingPlanCandidate],
    ) -> PlanRankingResult:
        feature_coverage = {
            "training_load": context.acute_load is not None
            and context.chronic_load is not None
            and context.observation_days >= 7,
            "weather": context.temperature_c is not None
            and context.weather_state in {"LIVE", "CACHED", "STALE"},
            "injury_triage": context.triage_urgency is not None,
        }
        cold_start = not feature_coverage["training_load"]
        return PlanRankingResult(
            ranked_candidates=tuple(candidates),
            ranker_version=self.version,
            abstained=cold_start,
            abstention_reason="INSUFFICIENT_OBSERVATIONS" if cold_start else None,
            confidence=None,
            feature_coverage=feature_coverage,
        )

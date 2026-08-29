"""Generate bounded workout candidates before any learned ranking step."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.safety_triage import TriageUrgency


class WorkoutType(StrEnum):
    REST_AND_SEEK_CARE = "REST_AND_SEEK_CARE"
    RECOVERY_RUN = "RECOVERY_RUN"
    EASY_RUN = "EASY_RUN"


@dataclass(frozen=True)
class TrainingPlanContext:
    triage_urgency: TriageUrgency | None
    observation_days: int
    acute_load: float | None
    chronic_load: float | None
    temperature_c: float | None
    weather_state: str


@dataclass(frozen=True)
class TrainingPlanCandidate:
    candidate_id: str
    workout_type: WorkoutType
    duration_minutes: int
    distance_km: float
    running_allowed: bool
    provenance_rule_ids: tuple[str, ...]


def generate_training_plan_candidates(
    context: TrainingPlanContext,
) -> tuple[TrainingPlanCandidate, ...]:
    if context.triage_urgency in {
        TriageUrgency.EMERGENCY,
        TriageUrgency.PROMPT_CLINICIAN,
    }:
        return (
            TrainingPlanCandidate(
                candidate_id="rest-and-seek-care",
                workout_type=WorkoutType.REST_AND_SEEK_CARE,
                duration_minutes=0,
                distance_km=0,
                running_allowed=False,
                provenance_rule_ids=("TRIAGE_BLOCKS_RUNNING",),
            ),
        )

    return (
        TrainingPlanCandidate(
            candidate_id="recovery-run",
            workout_type=WorkoutType.RECOVERY_RUN,
            duration_minutes=20,
            distance_km=3.0,
            running_allowed=True,
            provenance_rule_ids=("DETERMINISTIC_FALLBACK",),
        ),
    )

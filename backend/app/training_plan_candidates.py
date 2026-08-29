"""Generate bounded workout candidates before any ranking step.

Candidates are authored here from reviewed deterministic rules. A ranker
(deterministic today, possibly learned later) may only *reorder* what this
module returns -- it can never invent a candidate or change a candidate's
distance / duration / intensity (ADR 0002).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.safety_triage import TriageUrgency


class WorkoutType(StrEnum):
    REST_AND_SEEK_CARE = "REST_AND_SEEK_CARE"
    REST_DAY = "REST_DAY"
    RECOVERY_RUN = "RECOVERY_RUN"
    EASY_RUN = "EASY_RUN"
    STEADY_RUN = "STEADY_RUN"


# Ordinal intensity used by both the candidate table and the ranker's scoring
# curve: 0 rest .. 3 steady. Kept here so the two stay in lockstep.
INTENSITY_ORDINAL: dict[WorkoutType, int] = {
    WorkoutType.REST_AND_SEEK_CARE: 0,
    WorkoutType.REST_DAY: 0,
    WorkoutType.RECOVERY_RUN: 1,
    WorkoutType.EASY_RUN: 2,
    WorkoutType.STEADY_RUN: 3,
}


@dataclass(frozen=True)
class TrainingPlanContext:
    triage_urgency: TriageUrgency | None
    observation_days: int
    acute_load: float | None
    chronic_load: float | None
    temperature_c: float | None
    weather_state: str

    @property
    def acute_chronic_ratio(self) -> float | None:
        if self.acute_load is None or not self.chronic_load:
            return None
        return round(self.acute_load / self.chronic_load, 2)


@dataclass(frozen=True)
class TrainingPlanCandidate:
    candidate_id: str
    workout_type: WorkoutType
    duration_minutes: int
    distance_km: float
    running_allowed: bool
    provenance_rule_ids: tuple[str, ...]

    @property
    def intensity_ordinal(self) -> int:
        return INTENSITY_ORDINAL[self.workout_type]


_REST_AND_SEEK_CARE = TrainingPlanCandidate(
    candidate_id="rest-and-seek-care",
    workout_type=WorkoutType.REST_AND_SEEK_CARE,
    duration_minutes=0,
    distance_km=0,
    running_allowed=False,
    provenance_rule_ids=("TRIAGE_BLOCKS_RUNNING",),
)

_REST_DAY = TrainingPlanCandidate(
    candidate_id="rest-day",
    workout_type=WorkoutType.REST_DAY,
    duration_minutes=0,
    distance_km=0.0,
    running_allowed=True,
    provenance_rule_ids=("CONSERVATIVE_REST_OPTION",),
)
_RECOVERY_RUN = TrainingPlanCandidate(
    candidate_id="recovery-run",
    workout_type=WorkoutType.RECOVERY_RUN,
    duration_minutes=20,
    distance_km=3.0,
    running_allowed=True,
    provenance_rule_ids=("BOUNDED_RECOVERY_TEMPLATE",),
)
_EASY_RUN = TrainingPlanCandidate(
    candidate_id="easy-run",
    workout_type=WorkoutType.EASY_RUN,
    duration_minutes=40,
    distance_km=7.0,
    running_allowed=True,
    provenance_rule_ids=("BOUNDED_EASY_TEMPLATE",),
)
_STEADY_RUN = TrainingPlanCandidate(
    candidate_id="steady-run",
    workout_type=WorkoutType.STEADY_RUN,
    duration_minutes=45,
    distance_km=9.0,
    running_allowed=True,
    provenance_rule_ids=("BOUNDED_STEADY_TEMPLATE",),
)


def generate_training_plan_candidates(
    context: TrainingPlanContext,
) -> tuple[TrainingPlanCandidate, ...]:
    """The bounded option set for one day.

    * Emergency / prompt-clinician triage -> a single non-running option.
    * Self-care triage -> rest .. easy, no steady effort.
    * Otherwise -> the full rest .. steady ladder; the ranker picks the order.
    """
    if context.triage_urgency in {
        TriageUrgency.EMERGENCY,
        TriageUrgency.PROMPT_CLINICIAN,
    }:
        return (_REST_AND_SEEK_CARE,)

    if context.triage_urgency is TriageUrgency.SELF_CARE_NEXT_STEP:
        # A self-reported niggle: only rest or an easy recovery jog is on the
        # table -- no easy-pace volume day, no steady effort.
        return (_REST_DAY, _RECOVERY_RUN)

    return (_REST_DAY, _RECOVERY_RUN, _EASY_RUN, _STEADY_RUN)

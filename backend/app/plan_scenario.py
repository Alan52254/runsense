"""Plan Scenario: the facts a plan is evaluated against.

"Today" is the Plan Scenario with nothing overridden, so today's plan and an
explored plan are produced by the same code path and cannot drift apart.

A Scenario Override carries *facts about the Athlete's situation* -- date,
conditions, available time, what they reported. It has no field for distance,
duration, pace, intensity or workout type: ADR 0002 is enforced here by those
fields not existing, not by review. Candidate generation stays the exclusive
job of the reviewed deterministic rules in `training_plan_candidates`, and
ordering stays the exclusive job of `plan_ranking`; neither is modified by
anything in this module.

Two safety invariants hold for every override, including one authored by a
language model:

* An override can raise urgency but never lower it below what the Athlete's
  own recorded facts already imply (ADR 0001).
* A time budget filters which reviewed candidates are eligible. It never
  rewrites a candidate, and it never leaves the Athlete with nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as date_type
from typing import Mapping

from app.plan_ranking import CandidateScore, configured_plan_ranker
from app.safety_triage import TriageUrgency
from app.weather_pace import (
    MEASURED_BAND_ABOVE_OPTIMUM_C,
    MEASURED_BAND_BELOW_OPTIMUM_C,
    OPTIMUM_TEMPERATURE_C,
    speed_loss_pct_relative_to_normal,
)
from app.training_plan_candidates import (
    TrainingPlanCandidate,
    TrainingPlanContext,
    generate_training_plan_candidates,
)

# Ordered least to most urgent. Used only to guarantee an override can never
# move an Athlete down this list.
_URGENCY_RANK: dict[TriageUrgency, int] = {
    TriageUrgency.SELF_CARE_NEXT_STEP: 1,
    TriageUrgency.PROMPT_CLINICIAN: 2,
    TriageUrgency.EMERGENCY: 3,
}

_SEVERITY_BAND_URGENCY: dict[str, TriageUrgency] = {
    "SEVERE": TriageUrgency.PROMPT_CLINICIAN,
    "MODERATE": TriageUrgency.SELF_CARE_NEXT_STEP,
    "MILD": TriageUrgency.SELF_CARE_NEXT_STEP,
}

# The order overridden facts are reported back to the Athlete in. Stable so an
# explanation reads the same way twice.
_OVERRIDABLE_FACTS: tuple[str, ...] = (
    "local_date",
    "temperature_c",
    "humidity_pct",
    "available_minutes",
    "reported_body_part",
    "reported_severity_band",
)

DEFAULT_SCENARIO_LABEL = "TODAY"


def urgency_from_severity_band(severity_band: str | None) -> TriageUrgency | None:
    """The deterministic band-to-urgency mapping shared by every caller."""
    if not severity_band:
        return None
    return _SEVERITY_BAND_URGENCY.get(severity_band.upper())


def _max_urgency(
    left: TriageUrgency | None, right: TriageUrgency | None
) -> TriageUrgency | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if _URGENCY_RANK[left] >= _URGENCY_RANK[right] else right


@dataclass(frozen=True)
class AthleteFacts:
    """What is actually true for one Athlete on one Local Training Date."""

    local_date: date_type
    observation_days: int = 0
    acute_load: float | None = None
    chronic_load: float | None = None
    temperature_c: float | None = None
    humidity_pct: float | None = None
    weather_state: str = "UNAVAILABLE"
    reported_body_part: str | None = None
    reported_severity_band: str | None = None
    available_minutes: int | None = None
    city: str | None = None
    # Pacing facts: the athlete's curve, and what counts as a typical
    # evening for their city and month (routes/weather.py's reference).
    sex: str | None = None
    climate_reference_c: float | None = None


@dataclass(frozen=True)
class ScenarioOverride:
    """The sparse difference between a Plan Scenario and the Athlete's facts.

    This is the only artifact a language model may emit that influences
    computation. Adding a field here requires justifying it as a fact about
    the Athlete's situation -- never as a property of the workout.
    """

    local_date: date_type | None = None
    temperature_c: float | None = None
    humidity_pct: float | None = None
    available_minutes: int | None = None
    reported_body_part: str | None = None
    reported_severity_band: str | None = None
    label: str | None = None

    def stated_facts(self) -> tuple[str, ...]:
        return tuple(
            name for name in _OVERRIDABLE_FACTS if getattr(self, name) is not None
        )

    def is_empty(self) -> bool:
        return self.stated_facts() == ()


@dataclass(frozen=True)
class ResolvedScenario:
    """A Scenario Override merged onto the Athlete's facts; the only input
    plan evaluation accepts."""

    facts: AthleteFacts
    overridden_fields: tuple[str, ...]
    label: str
    triage_urgency: TriageUrgency | None

    @property
    def is_today(self) -> bool:
        return self.overridden_fields == ()

    @property
    def plan_context(self) -> TrainingPlanContext:
        """The existing context type, unchanged, so generation and ranking
        never have to learn about scenarios."""
        return TrainingPlanContext(
            triage_urgency=self.triage_urgency,
            observation_days=self.facts.observation_days,
            acute_load=self.facts.acute_load,
            chronic_load=self.facts.chronic_load,
            temperature_c=self.facts.temperature_c,
            weather_state=self.facts.weather_state,
        )


@dataclass(frozen=True)
class ScenarioEvaluation:
    """A Ranked Plan together with the scenario that produced it."""

    scenario: ResolvedScenario
    ranked_candidates: tuple[TrainingPlanCandidate, ...]
    ranker_version: str
    abstained: bool
    abstention_reason: str | None
    confidence: float | None
    reason_code: str
    feature_coverage: Mapping[str, bool]
    candidate_scores: tuple[CandidateScore, ...]
    excluded_by_time_budget: tuple[str, ...] = ()
    # % of running speed this scenario costs relative to a typical
    # evening for the Athlete's city and month. None when the scenario
    # has no temperature or no reference to compare against.
    speed_loss_pct: float | None = None
    # True when the scenario sits outside the published curve's measured
    # band, so the figure is an extrapolation and must be presented as one.
    pacing_is_extrapolated: bool = False


def resolve_scenario(
    facts: AthleteFacts, override: ScenarioOverride | None
) -> ResolvedScenario:
    """Merge an override onto the Athlete's facts, keeping safety monotonic."""
    override = override or ScenarioOverride()
    stated = override.stated_facts()

    merged = replace(
        facts,
        **{name: getattr(override, name) for name in stated},
    )

    # An override may report something worse than the record, never better.
    recorded_urgency = urgency_from_severity_band(facts.reported_severity_band)
    stated_urgency = urgency_from_severity_band(merged.reported_severity_band)

    return ResolvedScenario(
        facts=merged,
        overridden_fields=stated,
        label=override.label or DEFAULT_SCENARIO_LABEL,
        triage_urgency=_max_urgency(recorded_urgency, stated_urgency),
    )


def _within_time_budget(
    candidates: tuple[TrainingPlanCandidate, ...], available_minutes: int | None
) -> tuple[tuple[TrainingPlanCandidate, ...], tuple[str, ...]]:
    """Drop options the Athlete could not finish, never leaving them none."""
    if available_minutes is None:
        return candidates, ()

    eligible = tuple(c for c in candidates if c.duration_minutes <= available_minutes)
    if not eligible:
        # The gentlest reviewed option always remains available.
        gentlest = min(candidates, key=lambda c: c.duration_minutes)
        eligible = (gentlest,)

    excluded = tuple(
        c.candidate_id for c in candidates if c.candidate_id not in {e.candidate_id for e in eligible}
    )
    return eligible, excluded


def _pacing_for(facts: AthleteFacts) -> tuple[float | None, bool]:
    """How much speed this scenario costs, from the same facts the plan used.

    Returns no figure at all rather than a guess when the scenario has no
    temperature, or no typical-evening reference for the Athlete's city to
    compare it against.
    """
    if facts.temperature_c is None or facts.climate_reference_c is None:
        return None, False

    loss = speed_loss_pct_relative_to_normal(
        facts.temperature_c, facts.climate_reference_c, facts.sex
    )
    lowest_measured = OPTIMUM_TEMPERATURE_C - MEASURED_BAND_BELOW_OPTIMUM_C
    highest_measured = OPTIMUM_TEMPERATURE_C + MEASURED_BAND_ABOVE_OPTIMUM_C
    extrapolated = not (lowest_measured <= facts.temperature_c <= highest_measured)
    return round(loss, 2), extrapolated


def evaluate_scenario(scenario: ResolvedScenario) -> ScenarioEvaluation:
    """Generate the bounded candidate set for a scenario and order it.

    Pure with respect to the database: everything it needs is already in the
    Resolved Scenario.
    """
    context = scenario.plan_context
    candidates = generate_training_plan_candidates(context)

    # A time budget is an Athlete fact, but it must never widen what triage
    # has already narrowed to a single non-running option.
    running_is_blocked = any(not c.running_allowed for c in candidates)
    if running_is_blocked:
        eligible, excluded = candidates, ()
    else:
        eligible, excluded = _within_time_budget(candidates, scenario.facts.available_minutes)

    result = configured_plan_ranker().rank(context, eligible)
    speed_loss, extrapolated = _pacing_for(scenario.facts)

    return ScenarioEvaluation(
        scenario=scenario,
        ranked_candidates=result.ranked_candidates,
        ranker_version=result.ranker_version,
        abstained=result.abstained,
        abstention_reason=result.abstention_reason,
        confidence=result.confidence,
        reason_code=result.reason_code,
        feature_coverage=result.feature_coverage,
        candidate_scores=result.candidate_scores,
        excluded_by_time_budget=excluded,
        speed_loss_pct=speed_loss,
        pacing_is_extrapolated=extrapolated,
    )

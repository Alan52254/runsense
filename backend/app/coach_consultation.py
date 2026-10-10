"""Coach Consultation: the facts a Coach Conversation is grounded in.

Assembling these facts used to be inlined, identically, in both the streaming
and the non-streaming conversation handlers. Two copies of the same procedure
is two chances to drift, and neither copy was reachable from a test without
standing up HTTP and Postgres. This module owns the assembly, exposes one
verb, and reaches its data through narrow readers so it can be exercised in
memory.

It reads. It never decides urgency (that is `safety_triage`), never generates
a workout (that is `training_plan_candidates`), and never orders one (that is
`plan_ranking`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Any, Mapping, Protocol, Sequence

from app.evidence_retriever import EvidenceQuery
from app.injury_guidance import EvidencePassage
from app.plan_scenario import AthleteFacts
from app.safety_triage import TriageDecision, TriageUrgency, assess_safety_triage_text

# Re-exported: callers of the consultation state a query without needing to
# know which module retrieval lives in.
__all__ = [
    "CoachConsultation",
    "ConsultationFacts",
    "ConsultationRequest",
    "EvidenceQuery",
    "LatestSelfReport",
    "RecentActivitySummary",
    "RecentTrainingSummary",
]


@dataclass(frozen=True)
class LatestSelfReport:
    """The most recent thing the Athlete told us about their body."""

    local_training_date: date_type
    has_issue: bool
    severity_band: str | None
    body_part: str | None


@dataclass(frozen=True)
class RecentActivitySummary:
    """A compact, computed view of one recent session; never raw telemetry."""

    local_training_date: date_type
    distance_km: float | None
    duration_minutes: float
    average_heart_rate_bpm: int | None
    average_cadence_spm: int | None
    rpe: int | None


@dataclass(frozen=True)
class RecentTrainingSummary:
    """Bounded 28-day context supplied to the private health coach."""

    window_days: int
    activity_count: int
    total_distance_km: float
    total_duration_minutes: float
    average_heart_rate_bpm: int | None
    average_cadence_spm: int | None
    recent_activities: tuple[RecentActivitySummary, ...] = ()


@dataclass(frozen=True)
class ConsultationRequest:
    actor_id: str
    messages: Sequence[Mapping[str, Any]]
    body_part: str | None = None
    severity_band: str | None = None


@dataclass(frozen=True)
class ConsultationFacts:
    """Everything the coach is allowed to reason from, and nothing else."""

    local_date: date_type
    observation_days: int
    acute_load: float | None
    chronic_load: float | None
    load_ratio: float | None
    temperature_c: float | None
    humidity_pct: float | None
    weather_state: str
    body_part: str | None
    severity_band: str | None
    has_self_reported_issue: bool
    triage_decision: TriageDecision | None
    city: str | None = None
    evidence: tuple[EvidencePassage, ...] = field(default=())
    recent_training: RecentTrainingSummary | None = None

    @property
    def triage_urgency(self) -> TriageUrgency | None:
        return self.triage_decision.urgency if self.triage_decision else None

    @property
    def athlete_facts_for_planning(self) -> AthleteFacts:
        """The same facts, in the shape plan evaluation accepts."""
        return AthleteFacts(
            local_date=self.local_date,
            observation_days=self.observation_days,
            acute_load=self.acute_load,
            chronic_load=self.chronic_load,
            temperature_c=self.temperature_c,
            humidity_pct=self.humidity_pct,
            weather_state=self.weather_state,
            reported_body_part=self.body_part,
            reported_severity_band=self.severity_band,
            triage_urgency=self.triage_urgency,
            city=self.city,
        )


class AthleteFactsReader(Protocol):
    def read_athlete_facts(
        self, actor_id: str, local_date: date_type | None = None
    ) -> AthleteFacts: ...


class SelfReportReader(Protocol):
    def read_latest_self_report(self, actor_id: str) -> LatestSelfReport | None: ...


class EvidenceReader(Protocol):
    def retrieve(
        self, query: EvidenceQuery, *, limit: int = 5
    ) -> tuple[EvidencePassage, ...]: ...


class TrainingHistoryReader(Protocol):
    def read_recent_training_summary(
        self, actor_id: str, local_date: date_type | None = None
    ) -> RecentTrainingSummary | None: ...


def _latest_athlete_message(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(list(messages)):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


class CoachConsultation:
    def __init__(
        self,
        facts_reader: AthleteFactsReader,
        self_report_reader: SelfReportReader,
        evidence_reader: EvidenceReader,
        *,
        evidence_limit: int = 5,
        history_reader: TrainingHistoryReader | None = None,
    ) -> None:
        self._facts_reader = facts_reader
        self._self_report_reader = self_report_reader
        self._evidence_reader = evidence_reader
        self._evidence_limit = evidence_limit
        self._history_reader = history_reader or (
            facts_reader if hasattr(facts_reader, "read_recent_training_summary") else None
        )

    def assemble(self, request: ConsultationRequest) -> ConsultationFacts:
        facts = self._facts_reader.read_athlete_facts(request.actor_id)
        report = self._self_report_reader.read_latest_self_report(request.actor_id)

        # An explicit focus is what the Athlete is asking about right now, and
        # outranks whatever they last recorded.
        body_part = request.body_part or (report.body_part if report else None)
        severity_band = request.severity_band or (report.severity_band if report else None)
        has_issue = bool(request.body_part) or bool(report and report.has_issue)

        # The deterministic decision precedes retrieval and generation. The
        # consultation only orchestrates the established rule; it does not ask
        # evidence or a provider to decide urgency.
        latest_message = _latest_athlete_message(request.messages)
        triage_decision = assess_safety_triage_text(
            severity_band=severity_band,
            body_part=body_part,
            message=latest_message,
        )

        evidence = self._evidence_reader.retrieve(
            EvidenceQuery(
                free_text=latest_message,
                body_part=body_part,
                severity_band=severity_band,
                urgency=triage_decision.urgency.value if triage_decision else None,
            ),
            limit=self._evidence_limit,
        )
        recent_training = (
            self._history_reader.read_recent_training_summary(
                request.actor_id, facts.local_date
            )
            if self._history_reader is not None
            else None
        )

        return ConsultationFacts(
            local_date=facts.local_date,
            observation_days=facts.observation_days,
            acute_load=facts.acute_load,
            chronic_load=facts.chronic_load,
            load_ratio=_ratio(facts.acute_load, facts.chronic_load),
            temperature_c=facts.temperature_c,
            humidity_pct=facts.humidity_pct,
            weather_state=facts.weather_state,
            body_part=body_part,
            severity_band=severity_band,
            has_self_reported_issue=has_issue,
            triage_decision=triage_decision,
            city=facts.city,
            evidence=tuple(evidence),
            recent_training=recent_training,
        )


def _ratio(acute: float | None, chronic: float | None) -> float | None:
    if acute is None or not chronic:
        return None
    return round(acute / chronic, 2)

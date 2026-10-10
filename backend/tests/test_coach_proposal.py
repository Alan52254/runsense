"""A Coach Proposal is a Ranked Plan produced from stated facts.

The language model's only influence on computation is a Scenario Override.
These tests pin down that boundary: anything it emits that is malformed,
out of range, or shaped like a prescription produces no proposal at all,
and the conversation continues as explanation only.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.coach_proposal import CoachProposalService, ProposalOutcome
from app.plan_scenario import AthleteFacts
from app.safety_triage import TriageUrgency
from app.training_plan_candidates import WorkoutType

_TODAY = date(2026, 8, 30)


class FakeProposer:
    """Stands in for the language model."""

    def __init__(self, emits):
        self._emits = emits
        self.calls = 0

    def propose_override(self, messages, facts):
        self.calls += 1
        if isinstance(self._emits, Exception):
            raise self._emits
        return self._emits


def _facts(**overrides) -> AthleteFacts:
    base = dict(
        local_date=_TODAY,
        observation_days=20,
        acute_load=400.0,
        chronic_load=350.0,
        temperature_c=24.0,
        humidity_pct=60.0,
        weather_state="LIVE",
        sex="male",
        climate_reference_c=26.0,
    )
    base.update(overrides)
    return AthleteFacts(**base)


def _service(emits) -> CoachProposalService:
    return CoachProposalService(proposer=FakeProposer(emits))


def _messages(text="我今天只有 30 分鐘，小腿有點緊"):
    return ({"role": "user", "content": text},)


# --------------------------------------------------------------------------
# A well-formed set of facts becomes a proposal
# --------------------------------------------------------------------------


def test_stated_facts_become_a_proposal_backed_by_the_reviewed_engine():
    service = _service({"available_minutes": 30, "label": "只有 30 分鐘"})

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is not None
    assert outcome.proposal.evaluation.ranked_candidates
    assert all(
        c.duration_minutes <= 30 for c in outcome.proposal.evaluation.ranked_candidates
    )


def test_a_proposal_reports_which_facts_it_changed():
    service = _service({"temperature_c": 32.0, "available_minutes": 30})

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is not None
    assert outcome.proposal.evaluation.scenario.overridden_fields == (
        "temperature_c",
        "available_minutes",
    )


def test_a_proposal_carries_a_label_the_athlete_can_recognise():
    service = _service({"available_minutes": 30, "label": "Short session today"})

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is not None
    assert outcome.proposal.evaluation.scenario.label == "Short session today"


def test_a_proposal_changes_nothing_on_its_own():
    """It is a proposal until the Athlete accepts it."""
    service = _service({"available_minutes": 30})

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is not None
    assert outcome.proposal.accepted is False


# --------------------------------------------------------------------------
# Anything shaped like a prescription produces no proposal at all
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prescription",
    [
        {"distance_km": 12.0},
        {"duration_minutes": 90},
        {"pace_seconds_per_km": 300},
        {"intensity": 3},
        {"workout_type": "STEADY_RUN"},
        {"available_minutes": 30, "distance_km": 12.0},
    ],
)
def test_a_model_attempting_to_prescribe_produces_no_proposal(prescription):
    service = _service(prescription)

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is None
    assert outcome.reason == ProposalOutcome.REJECTED_SHAPE


def test_a_partially_valid_payload_is_discarded_whole():
    """There is no such state as a partly applied Scenario Override."""
    service = _service({"available_minutes": 30, "pace_seconds_per_km": 300})

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is None


@pytest.mark.parametrize(
    "payload",
    [
        {"temperature_c": 900.0},
        {"humidity_pct": -5},
        {"available_minutes": 0},
        {"reported_severity_band": "CATASTROPHIC"},
    ],
)
def test_an_out_of_range_fact_produces_no_proposal(payload):
    service = _service(payload)

    assert service.propose(_messages(), _facts()).proposal is None


@pytest.mark.parametrize("payload", [None, {}, "not a mapping", 42, []])
def test_no_usable_output_produces_no_proposal_and_no_error(payload):
    service = _service(payload)

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is None
    assert outcome.reason in {ProposalOutcome.NO_PROPOSAL, ProposalOutcome.REJECTED_SHAPE}


def test_a_provider_outage_produces_no_proposal_rather_than_an_error():
    service = _service(RuntimeError("provider down"))

    outcome = service.propose(_messages(), _facts())

    assert outcome.proposal is None
    assert outcome.reason == ProposalOutcome.UNAVAILABLE


# --------------------------------------------------------------------------
# Safety cannot be talked around
# --------------------------------------------------------------------------


def test_a_proposal_cannot_lower_urgency_the_athlete_already_recorded():
    service = _service({"reported_severity_band": "MILD"})

    outcome = service.propose(
        _messages(), _facts(reported_severity_band="SEVERE", reported_body_part="shin")
    )

    assert outcome.proposal is not None
    assert (
        outcome.proposal.evaluation.scenario.triage_urgency
        is TriageUrgency.PROMPT_CLINICIAN
    )


def test_a_proposal_cannot_unblock_running_when_triage_forbids_it():
    service = _service({"available_minutes": 90, "reported_severity_band": "MILD"})

    outcome = service.propose(_messages(), _facts(reported_severity_band="SEVERE"))

    assert outcome.proposal is not None
    assert [
        c.workout_type for c in outcome.proposal.evaluation.ranked_candidates
    ] == [WorkoutType.REST_AND_SEEK_CARE]


def test_the_model_is_asked_only_once_per_turn():
    service = _service({"available_minutes": 30})

    service.propose(_messages(), _facts())

    assert service._proposer.calls == 1  # type: ignore[attr-defined]

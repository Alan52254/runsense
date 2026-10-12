"""Coach Proposal: a Ranked Plan the Athlete has not accepted yet.

This is the whole of the language model's influence on computation. It may
state facts about the Athlete's situation -- how long they have, how hot the
day is, what they are feeling -- and nothing else. Those facts go through the
same Scenario Override schema every other caller uses, so the model cannot
state a distance, a duration, a pace, an intensity, or a workout type: those
fields do not exist (ADR 0002).

Every failure mode collapses to the same outcome: no proposal, and the
conversation carries on as explanation only. Malformed output, an
out-of-range value, a prescription attempt, a timeout, a provider outage --
all of them leave the Athlete's day exactly as it was. There is deliberately
no path that applies part of an override.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence

from pydantic import ValidationError

from app.plan_scenario import (
    AthleteFacts,
    ScenarioEvaluation,
    ScenarioOverride,
    evaluate_scenario,
    resolve_scenario,
)
from app.schemas import ScenarioOverrideRequest

logger = logging.getLogger("app.coach_proposal")


class ProposalOutcome(StrEnum):
    PROPOSED = "PROPOSED"
    # The model had nothing to propose -- an ordinary, expected result for a
    # question that is just a question.
    NO_PROPOSAL = "NO_PROPOSAL"
    # The model emitted something, and it was not a valid statement of facts.
    REJECTED_SHAPE = "REJECTED_SHAPE"
    # The model could not be reached at all.
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CoachProposal:
    evaluation: ScenarioEvaluation
    accepted: bool = False


@dataclass(frozen=True)
class ProposalResult:
    proposal: CoachProposal | None
    reason: ProposalOutcome


class ScenarioProposer(Protocol):
    """Whatever authors a candidate set of facts. Today, a language model."""

    def propose_override(
        self, messages: Sequence[Mapping[str, Any]], facts: AthleteFacts
    ) -> Mapping[str, Any] | None: ...


class CoachProposalService:
    def __init__(self, proposer: ScenarioProposer) -> None:
        self._proposer = proposer

    def propose(
        self, messages: Sequence[Mapping[str, Any]], facts: AthleteFacts
    ) -> ProposalResult:
        try:
            emitted = self._proposer.propose_override(messages, facts)
        except Exception:
            # An unreachable coach is not an error the Athlete should carry.
            logger.info("scenario proposer unavailable", exc_info=True)
            return ProposalResult(None, ProposalOutcome.UNAVAILABLE)

        override = _override_from(emitted)
        if override is None:
            reason = (
                ProposalOutcome.NO_PROPOSAL
                if emitted is None or emitted == {}
                else ProposalOutcome.REJECTED_SHAPE
            )
            return ProposalResult(None, reason)

        scenario = resolve_scenario(facts, override)
        return ProposalResult(
            CoachProposal(evaluation=evaluate_scenario(scenario)), ProposalOutcome.PROPOSED
        )


def _override_from(emitted: Any) -> ScenarioOverride | None:
    """Validate whole, or discard whole."""
    if not isinstance(emitted, Mapping) or not emitted:
        return None
    try:
        # The same boundary the HTTP endpoint uses: extra="forbid" plus the
        # absence of any prescription field.
        validated = ScenarioOverrideRequest(**dict(emitted))
    except (ValidationError, TypeError):
        logger.info("discarding malformed scenario override")
        return None

    override = ScenarioOverride(**validated.model_dump())
    # Facts that state nothing are not a proposal.
    return override if not override.is_empty() else None

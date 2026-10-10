"""Athlete-owned records of what the coach proposed and what they chose.

Only the stated facts are stored. The plan itself is always re-derived by the
reviewed engine from those facts, so an accepted proposal can never outlive or
contradict a change to the rules (ADR 0002). The plan summary that is stored
alongside is for the Athlete's own record of the conversation, not a source
anything is computed from.
"""

from __future__ import annotations

import json
import uuid
from datetime import date as date_type
from typing import Any

from sqlalchemy import Connection, text

from app.plan_scenario import ScenarioEvaluation, ScenarioOverride

_INSERT = text(
    """
    INSERT INTO coach_proposals (
        athlete_id, local_training_date, label, scenario_override,
        changed_facts, plan_summary, ranker_version, abstained
    ) VALUES (
        :athlete_id, :local_training_date, :label, CAST(:scenario_override AS jsonb),
        :changed_facts, CAST(:plan_summary AS jsonb), :ranker_version, :abstained
    )
    RETURNING id
    """
)

_SELECT_OPEN_PROPOSAL = text(
    """
    SELECT local_training_date
      FROM coach_proposals
     WHERE id = :proposal_id
       AND athlete_id = :athlete_id
       AND accepted_at IS NULL
       AND dismissed_at IS NULL
    """
)

_ACCEPT = text(
    """
    UPDATE coach_proposals
       SET accepted_at = now()
     WHERE id = :proposal_id
       AND athlete_id = :athlete_id
       AND accepted_at IS NULL
       AND dismissed_at IS NULL
    RETURNING id
    """
)

_DISMISS = text(
    """
    UPDATE coach_proposals
       SET dismissed_at = now()
     WHERE id = :proposal_id
       AND athlete_id = :athlete_id
       AND accepted_at IS NULL
       AND dismissed_at IS NULL
    RETURNING id
    """
)

_CLEAR_OTHER_ACCEPTED = text(
    """
    UPDATE coach_proposals
       SET accepted_at = NULL, dismissed_at = now()
     WHERE athlete_id = :athlete_id
       AND local_training_date = :local_training_date
       AND accepted_at IS NOT NULL
       AND id <> :proposal_id
    """
)

_SELECT_ACCEPTED_FOR_DAY = text(
    """
    SELECT scenario_override, label
      FROM coach_proposals
     WHERE athlete_id = :athlete_id
       AND local_training_date = :local_training_date
       AND accepted_at IS NOT NULL
     ORDER BY accepted_at DESC
     LIMIT 1
    """
)

_SELECT_RECENT = text(
    """
    SELECT id, local_training_date, label, changed_facts, plan_summary,
           abstained, proposed_at, accepted_at, dismissed_at
      FROM coach_proposals
     WHERE athlete_id = :athlete_id
     ORDER BY proposed_at DESC
     LIMIT :limit
    """
)

_OVERRIDE_FIELDS = (
    "local_date",
    "temperature_c",
    "humidity_pct",
    "available_minutes",
    "reported_body_part",
    "reported_severity_band",
    "label",
)


def record_proposal(
    tx: Connection, athlete_id: uuid.UUID, evaluation: ScenarioEvaluation
) -> uuid.UUID:
    """Store what was proposed. Nothing is applied by recording it."""
    scenario = evaluation.scenario
    stored_override = {
        name: getattr(scenario.facts, name if name != "local_date" else "local_date")
        for name in scenario.overridden_fields
    }
    if "local_date" in stored_override:
        stored_override["local_date"] = stored_override["local_date"].isoformat()

    row = tx.execute(
        _INSERT,
        {
            "athlete_id": athlete_id,
            "local_training_date": scenario.facts.local_date,
            "label": scenario.label,
            "scenario_override": json.dumps(stored_override),
            "changed_facts": list(scenario.overridden_fields),
            "plan_summary": json.dumps(
                {
                    "candidates": [
                        {
                            "candidate_id": candidate.candidate_id,
                            "workout_type": candidate.workout_type.value,
                            "duration_minutes": candidate.duration_minutes,
                            "distance_km": candidate.distance_km,
                            "running_allowed": candidate.running_allowed,
                        }
                        for candidate in evaluation.ranked_candidates
                    ],
                    "reason_code": evaluation.reason_code,
                    "confidence": evaluation.confidence,
                    "speed_loss_pct": evaluation.speed_loss_pct,
                    "shadow_evaluation": {
                        "ranker_version": evaluation.shadow_ranker_version,
                        "top_candidate_id": evaluation.shadow_top_candidate_id,
                        "used_fallback": evaluation.shadow_used_fallback,
                        "candidate_scores": [
                            {
                                "candidate_id": score.candidate_id,
                                "score": score.score,
                            }
                            for score in evaluation.shadow_candidate_scores
                        ],
                    }
                    if evaluation.shadow_ranker_version or evaluation.shadow_used_fallback
                    else None,
                }
            ),
            "ranker_version": evaluation.ranker_version,
            "abstained": evaluation.abstained,
        },
    ).first()
    return row.id


def accept_proposal(
    tx: Connection, athlete_id: uuid.UUID, proposal_id: uuid.UUID
) -> bool:
    """Accept one proposal, so that day is worked out from its facts.

    Accepting a second proposal for the same day supersedes the first rather
    than failing: the Athlete changed their mind, which is allowed.
    """
    open_proposal = tx.execute(
        _SELECT_OPEN_PROPOSAL, {"athlete_id": athlete_id, "proposal_id": proposal_id}
    ).first()
    if open_proposal is None:
        return False

    # Stand the previous acceptance down FIRST: at most one accepted proposal
    # may exist per day (migration 0025), so accepting before clearing would
    # collide with that index rather than superseding the earlier choice.
    tx.execute(
        _CLEAR_OTHER_ACCEPTED,
        {
            "athlete_id": athlete_id,
            "local_training_date": open_proposal.local_training_date,
            "proposal_id": proposal_id,
        },
    )
    return (
        tx.execute(_ACCEPT, {"athlete_id": athlete_id, "proposal_id": proposal_id}).first()
        is not None
    )


def dismiss_proposal(
    tx: Connection, athlete_id: uuid.UUID, proposal_id: uuid.UUID
) -> bool:
    """Decline one proposal. Nothing about the Athlete's day changes."""
    return (
        tx.execute(_DISMISS, {"athlete_id": athlete_id, "proposal_id": proposal_id}).first()
        is not None
    )


def accepted_override_for(
    tx: Connection, athlete_id: uuid.UUID, local_date: date_type
) -> ScenarioOverride | None:
    """The facts an accepted proposal established for this day, if any."""
    row = tx.execute(
        _SELECT_ACCEPTED_FOR_DAY,
        {"athlete_id": athlete_id, "local_training_date": local_date},
    ).first()
    if row is None:
        return None

    stored: dict[str, Any] = dict(row.scenario_override or {})
    stored["label"] = row.label
    if isinstance(stored.get("local_date"), str):
        stored["local_date"] = date_type.fromisoformat(stored["local_date"])

    return ScenarioOverride(
        **{name: stored.get(name) for name in _OVERRIDE_FIELDS}
    )


def list_recent(
    tx: Connection, athlete_id: uuid.UUID, limit: int = 20
) -> list[dict[str, Any]]:
    """How the Athlete's plan has been adapting, most recent first."""
    return [
        {
            "id": str(row.id),
            "local_date": row.local_training_date.isoformat(),
            "label": row.label,
            "changed_facts": list(row.changed_facts or []),
            "plan_summary": row.plan_summary,
            "abstained": row.abstained,
            "proposed_at": row.proposed_at.isoformat(),
            "outcome": (
                "ACCEPTED"
                if row.accepted_at
                else "DISMISSED"
                if row.dismissed_at
                else "OPEN"
            ),
        }
        for row in tx.execute(
            _SELECT_RECENT, {"athlete_id": athlete_id, "limit": limit}
        ).all()
    ]

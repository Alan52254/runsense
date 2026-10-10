from __future__ import annotations

import json
import uuid
from datetime import date as date_type
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import Connection, text

from app.clock import Clock, SystemClock
from app.db import actor_transaction, get_connection
from app.errors import ProfileTimezoneNotSetError
from app.llm_client import (
    COACH_UNAVAILABLE_MESSAGE,
    coach_turn,
    propose_scenario_override,
    provider_status,
    select_tone_variant,
    stream_coach_answer,
)
from app.coach_consultation import CoachConsultation, ConsultationRequest
from app.coach_handoff import coach_assigned_titles, share_proposal
from app.coach_proposal import CoachProposalService
from app.evidence_retriever import EvidenceQuery
from app.coach_proposal_store import (
    accept_proposal,
    dismiss_proposal,
    list_recent,
    record_proposal,
)
from app.plan_scenario import evaluate_scenario, resolve_scenario
from app.coach_consultation_pg import (
    GraphEvidenceReader,
    PostgresConsultationFactsReader,
    PostgresSelfReportReader,
)
from app.providers import CurrentActorProvider, ProfileTimezoneProvider
from app.recommendation_engine import compute_emotional_context, compute_recommendation
from pydantic import BaseModel, Field
from app.routes.activities import get_current_actor_provider, get_profile_timezone_provider
from app.schemas import GuidanceResponse, RecommendationResponse
from app.training_load_store import lock_athlete_training_load, recompute_training_load

router = APIRouter()
_system_clock = SystemClock()


def get_clock() -> Clock:
    return _system_clock


_SELECT_CACHE = text(
    "SELECT recommendation_json, tone_variant_id, computed_at FROM daily_guidance_cache "
    "WHERE athlete_id = :athlete_id AND local_date = :local_date"
)
_INSERT_CACHE = text(
    "INSERT INTO daily_guidance_cache (athlete_id, local_date, recommendation_json, tone_variant_id, computed_at) "
    "VALUES (:athlete_id, :local_date, CAST(:recommendation_json AS jsonb), :tone_variant_id, :computed_at)"
)
_SELECT_TODAYS_LOAD = text(
    "SELECT load_ratio, data_quality, acute_load, chronic_load FROM training_load_daily "
    "WHERE athlete_id = :athlete_id AND date = :local_date AND unit = 'AU'"
)
_PROPOSAL_DAY = text(
    "SELECT local_training_date FROM coach_proposals WHERE id = :id AND athlete_id = :a"
)
_SELECT_TONE_TEXT = text(
    "SELECT text, reviewed_by FROM tone_variant_templates WHERE tone_variant_id = :id"
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

class CoachChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    body_part: str | None = None
    severity_band: str | None = None

class CoachChatResponse(BaseModel):
    response: str
    # Whether a model actually produced `response`, or whether the coach could
    # not be reached and this is the standing safe notice. The interface says
    # so explicitly rather than leaving every caller to guess from the text.
    answer_source: Literal["MODEL", "UNAVAILABLE", "NOT_CONFIGURED"] = "MODEL"
    rag_citations: list[dict[str, str]] = []
    # A plan worked out from facts the Athlete stated in conversation. Absent
    # whenever they stated none, or whenever the model produced anything that
    # was not a valid statement of facts. It changes nothing until accepted.
    proposal: dict[str, Any] | None = None


class _StatedFactsProposer:
    """Hands the Coach Proposal seam facts that were already obtained.

    The turn fetches the reply and the stated facts together, so the proposal
    must not trigger a second provider round trip. Validation still happens at
    the same boundary -- this only removes the duplicate call.
    """

    def __init__(self, emitted: dict[str, Any] | None) -> None:
        self._emitted = emitted

    def propose_override(self, messages, facts):
        return self._emitted


def _serialise_proposal(result, tx, athlete_id) -> dict[str, Any] | None:
    """The Athlete-facing shape of a Coach Proposal.

    Carries what changed and what it produced, so the Athlete can judge the
    proposal rather than trust it. Nothing here has been applied.
    """
    if result.proposal is None:
        return None

    evaluation = result.proposal.evaluation
    scenario = evaluation.scenario
    # Recorded so the Athlete can act on it and later see what was proposed.
    proposal_id = record_proposal(tx, athlete_id, evaluation)
    # A day the coach scheduled is the coach's: the Athlete may send this
    # suggestion to the coach, but not apply it themselves (ADR 0003).
    coach_assigned = coach_assigned_titles(tx, athlete_id, scenario.facts.local_date)
    return {
        "id": str(proposal_id),
        "label": scenario.label,
        "changed_facts": list(scenario.overridden_fields),
        "accepted": result.proposal.accepted,
        "abstained": evaluation.abstained,
        "confidence": evaluation.confidence,
        "reason_code": evaluation.reason_code,
        "speed_loss_pct": evaluation.speed_loss_pct,
        "pacing_is_extrapolated": evaluation.pacing_is_extrapolated,
        "facts": {
            "local_date": scenario.facts.local_date.isoformat(),
            "temperature_c": scenario.facts.temperature_c,
            "humidity_pct": scenario.facts.humidity_pct,
            "available_minutes": scenario.facts.available_minutes,
            "reported_body_part": scenario.facts.reported_body_part,
            "reported_severity_band": scenario.facts.reported_severity_band,
        },
        "coach_assigned": coach_assigned,
        "self_apply_allowed": not coach_assigned,
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
    }


def _coach_context(facts, coach_assigned: list[str]) -> dict[str, Any]:
    """Build the provider context once, including fixed Safety Triage and
    what the coach has scheduled today (which the AI may not change)."""
    triage = facts.triage_decision
    return {
        "coach_assigned": coach_assigned,
        "city": facts.city,
        "temperature": facts.temperature_c,
        "humidity": facts.humidity_pct,
        "acute_load": facts.acute_load,
        "chronic_load": facts.chronic_load,
        "load_ratio": facts.load_ratio,
        "body_part": facts.body_part,
        "severity_band": facts.severity_band,
        "has_injury_issue": facts.has_self_reported_issue,
        "triage_urgency": triage.urgency.value if triage else None,
        "triage_rule_version": triage.rule_version if triage else None,
        "triage_matched_rules": list(triage.matched_rule_ids) if triage else [],
        "triage_running_allowed": triage.running_allowed if triage else None,
        "triage_next_step": triage.immediate_next_step if triage else None,
        "rag_passages": [
            {
                "title": passage.title,
                "publisher": passage.publisher,
                "text": passage.text,
                "source_url": passage.source_url,
            }
            for passage in facts.evidence
        ],
    }


@router.post("/guidance/chat", response_model=CoachChatResponse)
def chat_with_coach(
    req: CoachChatRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
    clock: Clock = Depends(get_clock),
) -> CoachChatResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    actor_id = uuid.UUID(actor_id_raw)
    with actor_transaction(conn, actor_id_raw) as tx:
        timezone_name = timezone_provider.get_profile_timezone(str(actor_id)) or "Asia/Taipei"
        try:
            today = clock.now_utc().astimezone(ZoneInfo(timezone_name)).date()
        except Exception:
            today = clock.now_utc().date()

        facts = CoachConsultation(
            facts_reader=PostgresConsultationFactsReader(tx, today),
            self_report_reader=PostgresSelfReportReader(tx),
            evidence_reader=GraphEvidenceReader(tx),
        ).assemble(
            ConsultationRequest(
                actor_id=str(actor_id),
                messages=[{"role": m.role, "content": m.content} for m in req.messages],
                body_part=req.body_part,
                severity_band=req.severity_band,
            )
        )
        coach_assigned = coach_assigned_titles(tx, actor_id, facts.local_date)

    context = _coach_context(facts, coach_assigned)
    rag_passages = context["rag_passages"]
    msg_dicts = [{"role": message.role, "content": message.content} for message in req.messages]

    # Provider calls must not hold an open database transaction. A slow or
    # unavailable coach leaves the rest of the Athlete's data path responsive.
    turn = coach_turn(msg_dicts, context, local_date=str(facts.local_date))
    proposal_result = CoachProposalService(
        proposer=_StatedFactsProposer(turn.scenario_override)
    ).propose(msg_dicts, facts.athlete_facts_for_planning)

    with actor_transaction(conn, actor_id_raw) as tx:
        proposal = _serialise_proposal(proposal_result, tx, actor_id)

    return CoachChatResponse(
        response=turn.answer.text,
        answer_source=turn.answer.source,
        rag_citations=rag_passages[:3],
        proposal=proposal,
    )

@router.post("/guidance/chat/stream")
def stream_chat_with_coach(
    req: CoachChatRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
    clock: Clock = Depends(get_clock),
):
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        timezone_name = timezone_provider.get_profile_timezone(str(actor_id)) or "Asia/Taipei"
        try:
            today = clock.now_utc().astimezone(ZoneInfo(timezone_name)).date()
        except Exception:
            today = clock.now_utc().date()

        facts = CoachConsultation(
            facts_reader=PostgresConsultationFactsReader(tx, today),
            self_report_reader=PostgresSelfReportReader(tx),
            evidence_reader=GraphEvidenceReader(tx),
        ).assemble(
            ConsultationRequest(
                actor_id=str(actor_id),
                messages=[{"role": m.role, "content": m.content} for m in req.messages],
                body_part=req.body_part,
                severity_band=req.severity_band,
            )
        )

        context = _coach_context(facts, coach_assigned_titles(tx, actor_id, facts.local_date))

        msg_dicts = [{"role": m.role, "content": m.content} for m in req.messages]

        # What the coach actually did, in the order it did it, each reported
        # with what it found. These are steps already performed -- the client
        # states them in the past tense -- not a simulated progress bar.
        scenario = resolve_scenario(facts.athlete_facts_for_planning, None)
        evaluation = evaluate_scenario(scenario)
        steps = [
            {
                "step": "READ_TRAINING_LOAD",
                "observation_days": facts.observation_days,
                "load_ratio": facts.load_ratio,
            },
            {
                "step": "REVIEWED_GUIDANCE",
                "count": len(facts.evidence),
                # What was actually consulted, so the Athlete can open it.
                "citations": [
                    {
                        "evidence_id": passage.evidence_id,
                        "title": passage.title,
                        "publisher": passage.publisher,
                        "source_url": passage.source_url,
                        "body_parts": list(getattr(passage, "body_parts", ()) or ()),
                        "phase": getattr(passage, "phase", None),
                    }
                    for passage in facts.evidence
                ],
            },
            {
                "step": "CONSIDERED_OPTIONS",
                "count": len(evaluation.ranked_candidates),
                "personalised": not evaluation.abstained,
            },
        ]

        stated_facts = propose_scenario_override(
            msg_dicts, {"local_date": str(facts.local_date)}
        )
        proposal_result = CoachProposalService(
            proposer=_StatedFactsProposer(stated_facts)
        ).propose(msg_dicts, facts.athlete_facts_for_planning)
        proposal = _serialise_proposal(proposal_result, tx, actor_id)

        def event_generator():
            for step in steps:
                yield f"data: {json.dumps(step, ensure_ascii=False)}\n\n"

            # Only real model output is streamed as content. If none
            # arrives, the Athlete is told that plainly rather than being
            # handed a failure notice dressed up as an answer.
            produced_any = False
            for delta_token in stream_coach_answer(msg_dicts, context):
                produced_any = True
                chunk = json.dumps({"delta": delta_token}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"

            if not produced_any:
                notice = json.dumps(
                    {"answer_source": "UNAVAILABLE", "text": COACH_UNAVAILABLE_MESSAGE},
                    ensure_ascii=False,
                )
                yield f"data: {notice}\n\n"

            if proposal is not None:
                payload = json.dumps({"proposal": proposal}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/guidance/today", response_model=GuidanceResponse)
def get_todays_guidance(
    llm_tone_enabled: bool = True,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
    clock: Clock = Depends(get_clock),
) -> GuidanceResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)

        timezone_name = timezone_provider.get_profile_timezone(str(actor_id))
        if not timezone_name:
            raise ProfileTimezoneNotSetError()
        try:
            today = clock.now_utc().astimezone(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError as exc:
            raise ProfileTimezoneNotSetError() from exc

        cached = tx.execute(
            _SELECT_CACHE, {"athlete_id": actor_id, "local_date": today}
        ).first()
        if cached is not None:
            return _response_from_cache(today, cached, tx)

        return _compute_and_cache(tx, actor_id, today, llm_tone_enabled)


def _compute_and_cache(
    tx: Connection, actor_id: uuid.UUID, today: date_type, llm_tone_enabled: bool
) -> GuidanceResponse:
    lock_athlete_training_load(tx, actor_id)
    recompute_training_load(tx, actor_id, today)

    load_row = tx.execute(
        _SELECT_TODAYS_LOAD, {"athlete_id": actor_id, "local_date": today}
    ).first()
    load_ratio = float(load_row.load_ratio) if load_row and load_row.load_ratio is not None else None
    data_quality = load_row.data_quality if load_row else "INSUFFICIENT"
    acute_load = float(load_row.acute_load) if load_row else 0.0
    chronic_load = float(load_row.chronic_load) if load_row else 0.0

    recommendation = compute_recommendation(load_ratio, data_quality)

    if llm_tone_enabled:
        emotional_context = compute_emotional_context(
            recommendation.adjustment_reason_code, acute_load, chronic_load
        )
        tone_variant_id = select_tone_variant(
            emotional_context.adjustment_reason_code, emotional_context.load_trend_direction
        )
    else:
        tone_variant_id = "NEUTRAL_FALLBACK"

    recommendation_dict = {
        "workout_type": recommendation.workout_type,
        "duration_minutes": recommendation.duration_minutes,
        "distance_km": recommendation.distance_km,
        "target_pace_sec_per_km": recommendation.target_pace_sec_per_km,
        "intensity_label": recommendation.intensity_label,
        "adjustment_reason_code": recommendation.adjustment_reason_code,
        "algorithm_version": recommendation.algorithm_version,
        "segments": list(recommendation.segments),
    }
    computed_at = tx.execute(text("SELECT now()")).scalar_one()

    tx.execute(
        _INSERT_CACHE,
        {
            "athlete_id": actor_id,
            "local_date": today,
            "recommendation_json": json.dumps(recommendation_dict),
            "tone_variant_id": tone_variant_id,
            "computed_at": computed_at,
        },
    )

    tone_row = tx.execute(_SELECT_TONE_TEXT, {"id": tone_variant_id}).one()
    return GuidanceResponse(
        local_date=today,
        recommendation=RecommendationResponse(**recommendation_dict),
        tone_variant_id=tone_variant_id,
        tone_text=tone_row.text,
        tone_reviewed_by=tone_row.reviewed_by,
        computed_at=computed_at,
    )


def _response_from_cache(today: date_type, cached: Any, tx: Connection) -> GuidanceResponse:
    recommendation_dict = (
        cached.recommendation_json
        if isinstance(cached.recommendation_json, dict)
        else json.loads(cached.recommendation_json)
    )
    if "segments" not in recommendation_dict:
        recommendation_dict["segments"] = list(
            compute_recommendation(None, "INSUFFICIENT").segments
        )
    tone_row = tx.execute(_SELECT_TONE_TEXT, {"id": cached.tone_variant_id}).one()
    return GuidanceResponse(
        local_date=today,
        recommendation=RecommendationResponse(**recommendation_dict),
        tone_variant_id=cached.tone_variant_id,
        tone_text=tone_row.text,
        tone_reviewed_by=tone_row.reviewed_by,
        computed_at=cached.computed_at,
    )


class ProposalOutcomeResponse(BaseModel):
    applied: bool
    # Why nothing was applied, when the Athlete could not have known:
    # COACH_SCHEDULED -- that day is the coach's; send it to the coach.
    reason: str | None = None


class ShareProposalResponse(BaseModel):
    room_ids: list[str]


@router.post("/guidance/proposals/{proposal_id}/accept", response_model=ProposalOutcomeResponse)
def accept_coach_proposal(
    proposal_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> ProposalOutcomeResponse:
    """Accept a Coach Proposal, so that day is worked out from its facts --
    unless the coach has scheduled that day (ADR 0003)."""
    actor_id_raw = actor_provider.get_current_actor_id()
    athlete_id = uuid.UUID(actor_id_raw)
    with actor_transaction(conn, actor_id_raw) as tx:
        day = tx.execute(_PROPOSAL_DAY, {"id": proposal_id, "a": athlete_id}).scalar_one_or_none()
        if day is not None and coach_assigned_titles(tx, athlete_id, day):
            return ProposalOutcomeResponse(applied=False, reason="COACH_SCHEDULED")
        applied = accept_proposal(tx, athlete_id, proposal_id)
    return ProposalOutcomeResponse(applied=applied)


@router.post("/guidance/proposals/{proposal_id}/share", response_model=ShareProposalResponse)
def share_coach_proposal(
    proposal_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> ShareProposalResponse:
    """Send a Coach Proposal to the Athlete's coach as a Coach Suggestion.
    Nothing is scheduled: the coach decides, in the team chat."""
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        rooms = share_proposal(tx, uuid.UUID(actor_id_raw), proposal_id)
    if rooms is None:
        raise HTTPException(status_code=404, detail={"error": "PROPOSAL_NOT_FOUND"})
    if not rooms:
        raise HTTPException(status_code=409, detail={"error": "NO_COACH",
                                                     "message": "你目前沒有加入任何隊伍，沒有教練可以傳送。"})
    return ShareProposalResponse(room_ids=rooms)


@router.post("/guidance/proposals/{proposal_id}/dismiss", response_model=ProposalOutcomeResponse)
def dismiss_coach_proposal(
    proposal_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> ProposalOutcomeResponse:
    """Decline a Coach Proposal. Nothing about the Athlete's day changes."""
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        dismiss_proposal(tx, uuid.UUID(actor_id_raw), proposal_id)
    return ProposalOutcomeResponse(applied=False)


@router.get("/guidance/proposals")
def list_coach_proposals(
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    """How this Athlete's plan has been adapting, and what they chose."""
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        return {"proposals": list_recent(tx, uuid.UUID(actor_id_raw))}


@router.get("/guidance/library")
def browse_guidance_library(
    body_part: str | None = None,
    phase: str | None = None,
    topic: str | None = None,
    limit: int = 12,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    """The reviewed guidance behind what the coach says.

    Browsable without having reported anything: an Athlete may want to read
    about a body area before it becomes a problem.
    """
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        passages = GraphEvidenceReader(tx).retrieve(
            EvidenceQuery(body_part=body_part, phase=phase, topic=topic),
            limit=max(1, min(limit, 40)),
        )

    return {
        "passages": [
            {
                "evidence_id": passage.evidence_id,
                "title": passage.title,
                "publisher": passage.publisher,
                "source_url": passage.source_url,
                "text": passage.text,
                "phase": getattr(passage, "phase", None),
                "phase_purpose": getattr(passage, "phase_purpose", None),
                "progression_criterion": getattr(passage, "progression_criterion", None),
                "body_parts": list(getattr(passage, "body_parts", ()) or ()),
            }
            for passage in passages
        ]
    }


class ProviderHealthResponse(BaseModel):
    """Whether this process can reach the coach provider right now."""

    configured: bool
    reachable: bool
    provider: str | None = None
    model: str | None = None
    detail: str | None = None


@router.get("/healthz/providers", response_model=ProviderHealthResponse)
def get_provider_health() -> ProviderHealthResponse:
    """Answer 'is the coach reachable from here?' in one request.

    Unauthenticated on purpose: it reports only reachability and never a
    credential, and an operator needs it precisely when nothing else works.
    """
    status = provider_status()
    return ProviderHealthResponse(
        configured=status.configured,
        reachable=status.reachable,
        provider=status.provider,
        model=status.model,
        detail=status.detail,
    )

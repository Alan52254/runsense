from __future__ import annotations

import json
import uuid
from datetime import date as date_type
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import Connection, text

from app.clock import Clock, SystemClock
from app.db import actor_transaction, get_connection
from app.errors import ProfileTimezoneNotSetError
from app.llm_client import ask_ai_health_coach, stream_ai_health_coach, select_tone_variant
from app.evidence_repository import PostgresEvidenceRepository
from app.evidence_retriever import GraphEvidenceRetriever
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
_SELECT_TONE_TEXT = text(
    "SELECT text, reviewed_by FROM tone_variant_templates WHERE tone_variant_id = :id"
)


_SELECT_LATEST_INJURY = text(
    """
    SELECT local_training_date, has_issue, severity_band, body_part
      FROM injury_reports
     WHERE athlete_id = :athlete_id
     ORDER BY local_training_date DESC
     LIMIT 1
    """
)

_SELECT_CHAT_PROFILE_WEATHER = text(
    "SELECT p.city, w.temperature_c, w.humidity_pct, w.fetched_at "
    "FROM athlete_profiles p LEFT JOIN weather_cache w ON w.city = p.city "
    "WHERE p.user_id = :athlete_id"
)

_SELECT_RAG_EVIDENCE = text(
    """
    SELECT title, publisher, text, source_url
      FROM evidence_passages
     WHERE approved = true
     ORDER BY evidence_id
     LIMIT 6
    """
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
    rag_citations: list[dict[str, str]] = []

@router.post("/guidance/chat", response_model=CoachChatResponse)
def chat_with_coach(
    req: CoachChatRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    timezone_provider: ProfileTimezoneProvider = Depends(get_profile_timezone_provider),
    clock: Clock = Depends(get_clock),
) -> CoachChatResponse:
    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        timezone_name = timezone_provider.get_profile_timezone(str(actor_id)) or "Asia/Taipei"
        try:
            today = clock.now_utc().astimezone(ZoneInfo(timezone_name)).date()
        except Exception:
            today = clock.now_utc().date()

        load_row = tx.execute(
            _SELECT_TODAYS_LOAD, {"athlete_id": actor_id, "local_date": today}
        ).first()

        injury_row = tx.execute(
            _SELECT_LATEST_INJURY, {"athlete_id": actor_id}
        ).first()
        weather_row = tx.execute(
            _SELECT_CHAT_PROFILE_WEATHER, {"athlete_id": actor_id}
        ).first()

        # Build dynamic search query from athlete's latest message and body context
        latest_user_text = ""
        for m in reversed(req.messages):
            if m.role == "user":
                latest_user_text = m.content
                break

        query_tokens = [latest_user_text]
        if req.body_part:
            query_tokens.append(req.body_part)
        elif injury_row and injury_row.body_part:
            query_tokens.append(injury_row.body_part)

        combined_query = " ".join(query_tokens)

        # Graph RAG knowledge traversal
        repo = PostgresEvidenceRepository(tx)
        graph = repo.load_graph("sports-medicine-v1")
        retriever = GraphEvidenceRetriever(graph)
        retrieved_nodes = retriever.retrieve(combined_query, limit=5)

        rag_passages = [
            {
                "title": r.title,
                "publisher": r.publisher,
                "text": r.text,
                "source_url": r.source_url,
            }
            for r in retrieved_nodes
        ]

        context = {
            "city": weather_row.city if weather_row else None,
            "temperature": float(weather_row.temperature_c) if weather_row and weather_row.temperature_c is not None else None,
            "humidity": float(weather_row.humidity_pct) if weather_row and weather_row.humidity_pct is not None else None,
            "acute_load": float(load_row.acute_load) if load_row and load_row.acute_load is not None else None,
            "chronic_load": float(load_row.chronic_load) if load_row and load_row.chronic_load is not None else None,
            "load_ratio": float(load_row.load_ratio) if load_row and load_row.load_ratio is not None else None,
            "body_part": req.body_part or (injury_row.body_part if injury_row else None),
            "severity_band": req.severity_band or (injury_row.severity_band if injury_row else None),
            "has_injury_issue": injury_row.has_issue if injury_row else bool(req.body_part),
            "rag_passages": rag_passages,
        }

        msg_dicts = [{"role": m.role, "content": m.content} for m in req.messages]
        reply_text = ask_ai_health_coach(msg_dicts, context)
        return CoachChatResponse(
            response=reply_text,
            rag_citations=rag_passages[:3],
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

        load_row = tx.execute(
            _SELECT_TODAYS_LOAD, {"athlete_id": actor_id, "local_date": today}
        ).first()

        injury_row = tx.execute(
            _SELECT_LATEST_INJURY, {"athlete_id": actor_id}
        ).first()
        weather_row = tx.execute(
            _SELECT_CHAT_PROFILE_WEATHER, {"athlete_id": actor_id}
        ).first()

        latest_user_text = ""
        for m in reversed(req.messages):
            if m.role == "user":
                latest_user_text = m.content
                break

        query_tokens = [latest_user_text]
        if req.body_part:
            query_tokens.append(req.body_part)
        elif injury_row and injury_row.body_part:
            query_tokens.append(injury_row.body_part)

        combined_query = " ".join(query_tokens)

        repo = PostgresEvidenceRepository(tx)
        graph = repo.load_graph("sports-medicine-v1")
        retriever = GraphEvidenceRetriever(graph)
        retrieved_nodes = retriever.retrieve(combined_query, limit=5)

        rag_passages = [
            {
                "title": r.title,
                "publisher": r.publisher,
                "text": r.text,
                "source_url": r.source_url,
            }
            for r in retrieved_nodes
        ]

        context = {
            "city": weather_row.city if weather_row else None,
            "temperature": float(weather_row.temperature_c) if weather_row and weather_row.temperature_c is not None else None,
            "humidity": float(weather_row.humidity_pct) if weather_row and weather_row.humidity_pct is not None else None,
            "acute_load": float(load_row.acute_load) if load_row and load_row.acute_load is not None else None,
            "chronic_load": float(load_row.chronic_load) if load_row and load_row.chronic_load is not None else None,
            "load_ratio": float(load_row.load_ratio) if load_row and load_row.load_ratio is not None else None,
            "body_part": req.body_part or (injury_row.body_part if injury_row else None),
            "severity_band": req.severity_band or (injury_row.severity_band if injury_row else None),
            "has_injury_issue": injury_row.has_issue if injury_row else bool(req.body_part),
            "rag_passages": rag_passages,
        }

        msg_dicts = [{"role": m.role, "content": m.content} for m in req.messages]

        def event_generator():
            for delta_token in stream_ai_health_coach(msg_dicts, context):
                chunk = json.dumps({"delta": delta_token}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"
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

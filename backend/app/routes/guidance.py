from __future__ import annotations

import json
import uuid
from datetime import date as date_type
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app.clock import Clock, SystemClock
from app.db import actor_transaction, get_connection
from app.errors import ProfileTimezoneNotSetError
from app.llm_client import select_tone_variant
from app.providers import CurrentActorProvider, ProfileTimezoneProvider
from app.recommendation_engine import compute_emotional_context, compute_recommendation
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

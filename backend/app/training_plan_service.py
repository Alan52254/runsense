"""Actor-scoped assembly of auditable daily training-plan candidates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Connection, text

from app.db import actor_transaction
from app.errors import ProfileTimezoneNotSetError
from app.plan_ranking import configured_plan_ranker
from app.safety_triage import TriageUrgency
from app.training_plan_candidates import TrainingPlanContext, generate_training_plan_candidates

# Same windows the Weather endpoint uses (routes/weather.py): a cache row is
# fresh for 10 minutes, usable-but-stale for 3 hours, and unusable after that.
_CACHED_WINDOW = timedelta(minutes=10)
_STALE_WINDOW = timedelta(hours=3)


def _weather_from_cache(fetched_at: datetime | None) -> str:
    if fetched_at is None:
        return "UNAVAILABLE"
    now = datetime.now(UTC)
    at = fetched_at if fetched_at.tzinfo is not None else fetched_at.replace(tzinfo=UTC)
    age = now - at
    if age < _CACHED_WINDOW:
        return "CACHED"
    if age < _STALE_WINDOW:
        return "STALE"
    return "UNAVAILABLE"


class TrainingPlanService:
    def __init__(self, conn: Connection):
        self._conn = conn

    def get_today(self, actor_id: uuid.UUID) -> dict[str, object]:
        with actor_transaction(self._conn, str(actor_id)) as tx:
            profile = tx.execute(
                text("SELECT timezone, city FROM athlete_profiles WHERE user_id = :actor_id"),
                {"actor_id": actor_id},
            ).first()
            if profile is None or not profile.timezone:
                raise ProfileTimezoneNotSetError()
            try:
                local_date = datetime.now(UTC).astimezone(ZoneInfo(profile.timezone)).date()
            except ZoneInfoNotFoundError as exc:
                raise ProfileTimezoneNotSetError() from exc

            load = tx.execute(
                text(
                    "SELECT acute_load, chronic_load, observation_days "
                    "FROM training_load_daily WHERE athlete_id = :actor_id AND unit = 'AU' "
                    "AND date <= :local_date ORDER BY date DESC LIMIT 1"
                ),
                {"actor_id": actor_id, "local_date": local_date},
            ).first()
            weather = (
                tx.execute(
                    text(
                        "SELECT temperature_c, fetched_at FROM weather_cache "
                        "WHERE city = :city ORDER BY fetched_at DESC LIMIT 1"
                    ),
                    {"city": profile.city},
                ).first()
                if profile.city
                else None
            )
            injury = tx.execute(
                text(
                    "SELECT severity_band FROM injury_reports WHERE athlete_id = :actor_id "
                    "AND local_training_date = :local_date ORDER BY reported_at DESC LIMIT 1"
                ),
                {"actor_id": actor_id, "local_date": local_date},
            ).first()

            urgency = None
            if injury and injury.severity_band == "SEVERE":
                urgency = TriageUrgency.PROMPT_CLINICIAN
            elif injury and injury.severity_band in {"MILD", "MODERATE"}:
                urgency = TriageUrgency.SELF_CARE_NEXT_STEP

            weather_state = _weather_from_cache(weather.fetched_at if weather else None)
            temperature_c = (
                float(weather.temperature_c)
                if weather is not None
                and weather.temperature_c is not None
                and weather_state != "UNAVAILABLE"
                else None
            )
            if temperature_c is None and profile.city:
                from app.climate_normals import get_climate_normal
                normal = get_climate_normal(profile.city, local_date.month)
                if normal is not None:
                    temperature_c = float(normal.mean_c)
                    weather_state = "CACHED"

            context = TrainingPlanContext(
                triage_urgency=urgency,
                observation_days=int(load.observation_days) if load else 0,
                acute_load=float(load.acute_load) if load else None,
                chronic_load=float(load.chronic_load) if load else None,
                temperature_c=temperature_c,
                weather_state=weather_state,
            )
            candidates = generate_training_plan_candidates(context)
            result = configured_plan_ranker().rank(context, candidates)
            score_by_id = {s.candidate_id: s for s in result.candidate_scores}
            return {
                "local_date": local_date.isoformat(),
                "ranker_version": result.ranker_version,
                "abstained": result.abstained,
                "abstention_reason": result.abstention_reason,
                "confidence": result.confidence,
                "reason_code": result.reason_code,
                "feature_coverage": dict(result.feature_coverage),
                "inputs": {
                    "acute_load": context.acute_load,
                    "chronic_load": context.chronic_load,
                    "acute_chronic_ratio": context.acute_chronic_ratio,
                    "observation_days": context.observation_days,
                    "temperature_c": context.temperature_c,
                    "weather_state": context.weather_state,
                    "triage_urgency": urgency.value if urgency else None,
                },
                "candidates": [
                    {
                        "candidate_id": item.candidate_id,
                        "workout_type": item.workout_type.value,
                        "duration_minutes": item.duration_minutes,
                        "distance_km": item.distance_km,
                        "running_allowed": item.running_allowed,
                        "provenance_rule_ids": list(item.provenance_rule_ids),
                        "score": score_by_id[item.candidate_id].score
                        if item.candidate_id in score_by_id
                        else None,
                        "rationale": list(score_by_id[item.candidate_id].rationale)
                        if item.candidate_id in score_by_id
                        else [],
                    }
                    for item in result.ranked_candidates
                ],
            }

"""Actor-scoped assembly of auditable daily training-plan candidates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Connection, text

from app.db import actor_transaction
from app.errors import ProfileTimezoneNotSetError
from app.plan_ranking import DeterministicPlanRanker
from app.safety_triage import TriageUrgency
from app.training_plan_candidates import TrainingPlanContext, generate_training_plan_candidates


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
            weather = tx.execute(
                text(
                    "SELECT temperature_c, fetched_at FROM weather_cache "
                    "WHERE city = :city"
                ),
                {"city": profile.city},
            ).first() if profile.city else None
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
                urgency = TriageUrgency.SELF_CARE

            context = TrainingPlanContext(
                triage_urgency=urgency,
                observation_days=int(load.observation_days) if load else 0,
                acute_load=float(load.acute_load) if load else None,
                chronic_load=float(load.chronic_load) if load else None,
                temperature_c=float(weather.temperature_c) if weather else None,
                weather_state="CACHED" if weather else "UNAVAILABLE",
            )
            candidates = generate_training_plan_candidates(context)
            result = DeterministicPlanRanker().rank(context, candidates)
            return {
                "local_date": local_date.isoformat(),
                "ranker_version": result.ranker_version,
                "abstained": result.abstained,
                "abstention_reason": result.abstention_reason,
                "confidence": result.confidence,
                "feature_coverage": dict(result.feature_coverage),
                "candidates": [
                    {
                        "candidate_id": item.candidate_id,
                        "workout_type": item.workout_type.value,
                        "duration_minutes": item.duration_minutes,
                        "distance_km": item.distance_km,
                        "running_allowed": item.running_allowed,
                        "provenance_rule_ids": list(item.provenance_rule_ids),
                    }
                    for item in result.ranked_candidates
                ],
            }

"""Actor-scoped assembly of auditable daily training-plan candidates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Connection, text

from app.db import actor_transaction
from app.coach_proposal_store import accepted_override_for
from app.errors import ProfileTimezoneNotSetError
from app.plan_scenario import (
    AthleteFacts,
    ScenarioOverride,
    ScenarioEvaluation,
    evaluate_scenario,
    resolve_scenario,
)

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
        """Today is the Plan Scenario with nothing overridden."""
        return self.evaluate(actor_id, None)

    def evaluate(
        self, actor_id: uuid.UUID, override: ScenarioOverride | None
    ) -> dict[str, object]:
        with actor_transaction(self._conn, str(actor_id)) as tx:
            facts = self._read_athlete_facts(tx, actor_id, override)

            # A proposal the Athlete accepted established facts for that day.
            # It is composed with anything the caller states now and resolved
            # ONCE against the Athlete's recorded facts -- resolving twice
            # would hide the recorded severity band behind the accepted
            # override and let an accepted proposal lower urgency (ADR 0001).
            accepted = accepted_override_for(tx, actor_id, facts.local_date)
            effective = (
                accepted.merged_with(override) if accepted is not None else override
            )

            return _serialise(evaluate_scenario(resolve_scenario(facts, effective)))

    def _read_athlete_facts(
        self, tx: Connection, actor_id: uuid.UUID, override: ScenarioOverride | None
    ) -> AthleteFacts:
        profile = tx.execute(
            text("SELECT timezone, city, sex FROM athlete_profiles WHERE user_id = :actor_id"),
            {"actor_id": actor_id},
        ).first()
        if profile is None or not profile.timezone:
            raise ProfileTimezoneNotSetError()
        try:
            local_date = datetime.now(UTC).astimezone(ZoneInfo(profile.timezone)).date()
        except ZoneInfoNotFoundError as exc:
            raise ProfileTimezoneNotSetError() from exc

        # Facts are read for the day the Athlete is asking about.
        if override is not None and override.local_date is not None:
            local_date = override.local_date

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
                    "SELECT temperature_c, humidity_pct, fetched_at FROM weather_cache "
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

        humidity_pct = (
            float(weather.humidity_pct)
            if weather is not None
            and weather.humidity_pct is not None
            and weather_state != "UNAVAILABLE"
            else None
        )

        climate_reference_c: float | None = None
        if profile.city:
            from app.climate_normals import get_climate_normal

            reference_normal = get_climate_normal(profile.city, local_date.month)
            if reference_normal is not None:
                climate_reference_c = float(reference_normal.mean_c)

        return AthleteFacts(
            local_date=local_date,
            observation_days=int(load.observation_days) if load else 0,
            acute_load=float(load.acute_load) if load else None,
            chronic_load=float(load.chronic_load) if load else None,
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            weather_state=weather_state,
            reported_severity_band=injury.severity_band if injury else None,
            city=profile.city,
            sex=profile.sex,
            climate_reference_c=climate_reference_c,
        )


def _serialise(evaluation: ScenarioEvaluation) -> dict[str, object]:
    """The wire shape. `today` and an explored scenario share it exactly."""
    scenario = evaluation.scenario
    context = scenario.plan_context
    score_by_id = {s.candidate_id: s for s in evaluation.candidate_scores}
    return {
        "local_date": scenario.facts.local_date.isoformat(),
        "ranker_version": evaluation.ranker_version,
        "abstained": evaluation.abstained,
        "abstention_reason": evaluation.abstention_reason,
        "confidence": evaluation.confidence,
        "reason_code": evaluation.reason_code,
        "feature_coverage": dict(evaluation.feature_coverage),
        "shadow_evaluation": {
            "ranker_version": evaluation.shadow_ranker_version,
            "top_candidate_id": evaluation.shadow_top_candidate_id,
            "used_fallback": evaluation.shadow_used_fallback,
            "candidate_scores": [
                {"candidate_id": score.candidate_id, "score": score.score}
                for score in evaluation.shadow_candidate_scores
            ],
        }
        if evaluation.shadow_ranker_version or evaluation.shadow_used_fallback
        else None,
        "scenario": {
            "label": scenario.label,
            "is_today": scenario.is_today,
            "overridden_fields": list(scenario.overridden_fields),
            "available_minutes": scenario.facts.available_minutes,
            "humidity_pct": scenario.facts.humidity_pct,
            "excluded_by_time_budget": list(evaluation.excluded_by_time_budget),
            "speed_loss_pct": evaluation.speed_loss_pct,
            "pacing_is_extrapolated": evaluation.pacing_is_extrapolated,
        },
        "inputs": {
            "acute_load": context.acute_load,
            "chronic_load": context.chronic_load,
            "acute_chronic_ratio": context.acute_chronic_ratio,
            "observation_days": context.observation_days,
            "temperature_c": context.temperature_c,
            "weather_state": context.weather_state,
            "triage_urgency": (
                scenario.triage_urgency.value if scenario.triage_urgency else None
            ),
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
            for item in evaluation.ranked_candidates
        ],
    }

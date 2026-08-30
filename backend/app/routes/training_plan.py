from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.db import get_connection
from app.plan_model_report import PlanModelReportService
from app.plan_scenario import ScenarioOverride
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.schemas import ScenarioOverrideRequest
from app.training_plan_service import TrainingPlanService

router = APIRouter()


def get_training_plan_service(conn: Connection = Depends(get_connection)) -> TrainingPlanService:
    return TrainingPlanService(conn)


def get_plan_model_report_service(
    conn: Connection = Depends(get_connection),
) -> PlanModelReportService:
    return PlanModelReportService(conn)


@router.get("/training-plan/today")
def get_training_plan_today(
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: TrainingPlanService = Depends(get_training_plan_service),
) -> dict[str, Any]:
    actor_id = uuid.UUID(actor_provider.get_current_actor_id())
    return service.get_today(actor_id)


@router.post("/training-plan/evaluate")
def evaluate_training_plan_scenario(
    req: ScenarioOverrideRequest,
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: TrainingPlanService = Depends(get_training_plan_service),
) -> dict[str, Any]:
    """Evaluate the reviewed plan pipeline against a stated set of facts.

    An empty body is today, and takes the same path as GET /training-plan/today.
    """
    actor_id = uuid.UUID(actor_provider.get_current_actor_id())
    return service.evaluate(actor_id, ScenarioOverride(**req.model_dump()))


@router.get("/training-plan/model-report")
def get_training_plan_model_report(
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: PlanModelReportService = Depends(get_plan_model_report_service),
) -> dict[str, Any]:
    actor_id = uuid.UUID(actor_provider.get_current_actor_id())
    return service.get_report(actor_id)

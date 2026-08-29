from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.db import get_connection
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.training_plan_service import TrainingPlanService

router = APIRouter()


def get_training_plan_service(conn: Connection = Depends(get_connection)) -> TrainingPlanService:
    return TrainingPlanService(conn)


@router.get("/training-plan/today")
def get_training_plan_today(
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: TrainingPlanService = Depends(get_training_plan_service),
) -> dict[str, Any]:
    actor_id = uuid.UUID(actor_provider.get_current_actor_id())
    return service.get_today(actor_id)

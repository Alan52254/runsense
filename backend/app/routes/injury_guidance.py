from __future__ import annotations

import uuid
from typing import Protocol

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection

from app.db import get_connection
from app.health_guidance_service import SqlInjuryGuidanceService
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.safety_triage import TriageUrgency


router = APIRouter(tags=["injury-guidance"])


class CreateInjuryGuidanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    injury_report_id: uuid.UUID
    unable_to_bear_weight: bool = False
    visible_deformity: bool = False
    uncontrolled_bleeding: bool = False
    chest_pain_or_breathing_difficulty: bool = False
    new_numbness_or_weakness: bool = False
    head_injury_with_neurological_symptoms: bool = False
    hot_swollen_joint_with_fever: bool = False
    collapse_confusion_or_extreme_heat_illness: bool = False
    localized_bone_pain_worse_with_weight_bearing: bool = False


class GuidanceCitationResponse(BaseModel):
    evidence_id: str
    title: str
    publisher: str
    source_url: str


class InjuryGuidanceResponse(BaseModel):
    injury_report_id: uuid.UUID
    urgency: TriageUrgency
    running_allowed: bool
    summary: str
    next_steps: list[str]
    citations: list[GuidanceCitationResponse]
    disclaimer: str
    rule_version: str
    matched_rule_ids: list[str]
    provider_name: str
    used_fallback: bool
    fallback_reason: str | None


class InjuryGuidanceService(Protocol):
    def create(
        self,
        actor_id: uuid.UUID,
        request: CreateInjuryGuidanceRequest,
    ) -> InjuryGuidanceResponse | dict: ...


def get_injury_guidance_service(
    conn: Connection = Depends(get_connection),
) -> InjuryGuidanceService:
    return SqlInjuryGuidanceService(conn)


@router.post("/injury-guidance", response_model=InjuryGuidanceResponse)
def create_injury_guidance(
    payload: CreateInjuryGuidanceRequest,
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: InjuryGuidanceService = Depends(get_injury_guidance_service),
) -> InjuryGuidanceResponse | dict:
    actor_id = uuid.UUID(actor_provider.get_current_actor_id())
    return service.create(actor_id, payload)

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.injury_guidance import (
    get_current_actor_provider,
    get_injury_guidance_service,
    router,
)
from app.safety_triage import TriageUrgency


class ActorProvider:
    def __init__(self, actor_id: uuid.UUID):
        self.actor_id = actor_id

    def get_current_actor_id(self) -> str:
        return str(self.actor_id)


class FakeGuidanceService:
    def __init__(self):
        self.call = None

    def create(self, actor_id, request):
        self.call = (actor_id, request)
        return {
            "injury_report_id": str(request.injury_report_id),
            "urgency": TriageUrgency.EMERGENCY,
            "running_allowed": False,
            "summary": "停止跑步並立即尋求緊急醫療協助。",
            "next_steps": ["停止跑步"],
            "citations": [],
            "disclaimer": "僅供一般資訊，不能取代專業醫療評估。",
            "rule_version": "safety-triage-v1",
            "matched_rule_ids": ["RED_FLAG_CARDIORESPIRATORY"],
            "provider_name": "static-fallback",
            "used_fallback": True,
            "fallback_reason": "PROVIDER_UNAVAILABLE",
        }


def test_route_uses_verified_actor_and_does_not_accept_athlete_id():
    actor_id = uuid.uuid4()
    report_id = uuid.uuid4()
    service = FakeGuidanceService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_actor_provider] = lambda: ActorProvider(actor_id)
    app.dependency_overrides[get_injury_guidance_service] = lambda: service

    response = TestClient(app).post(
        "/injury-guidance",
        json={
            "injury_report_id": str(report_id),
            "chest_pain_or_breathing_difficulty": True,
        },
    )

    assert response.status_code == 200
    assert service.call[0] == actor_id
    assert service.call[1].injury_report_id == report_id
    assert response.json()["urgency"] == "EMERGENCY"

    rejected = TestClient(app).post(
        "/injury-guidance",
        json={
            "injury_report_id": str(report_id),
            "athlete_id": str(uuid.uuid4()),
        },
    )
    assert rejected.status_code == 422

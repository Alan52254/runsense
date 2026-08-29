import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.training_plan import (
    get_current_actor_provider,
    get_training_plan_service,
    router,
)


class ActorProvider:
    def __init__(self, actor_id):
        self.actor_id = actor_id

    def get_current_actor_id(self):
        return str(self.actor_id)


class FakeTrainingPlanService:
    def __init__(self):
        self.actor_id = None

    def get_today(self, actor_id):
        self.actor_id = actor_id
        return {
            "local_date": "2026-08-29",
            "ranker_version": "deterministic-plan-ranker-v1",
            "abstained": True,
            "abstention_reason": "INSUFFICIENT_OBSERVATIONS",
            "confidence": None,
            "feature_coverage": {
                "training_load": False,
                "weather": False,
                "injury_triage": False,
            },
            "candidates": [
                {
                    "candidate_id": "recovery-run",
                    "workout_type": "RECOVERY_RUN",
                    "duration_minutes": 20,
                    "distance_km": 3.0,
                    "running_allowed": True,
                    "provenance_rule_ids": ["DETERMINISTIC_FALLBACK"],
                }
            ],
        }


def test_training_plan_route_uses_verified_actor_and_exposes_abstention_metadata():
    actor_id = uuid.uuid4()
    service = FakeTrainingPlanService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_actor_provider] = lambda: ActorProvider(actor_id)
    app.dependency_overrides[get_training_plan_service] = lambda: service

    response = TestClient(app).get("/training-plan/today")

    assert response.status_code == 200
    assert service.actor_id == actor_id
    body = response.json()
    assert body["abstained"] is True
    assert body["confidence"] is None
    assert body["feature_coverage"]["training_load"] is False
    assert body["candidates"][0]["candidate_id"] == "recovery-run"

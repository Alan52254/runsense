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
            "ranker_version": "deterministic-plan-ranker-v2",
            "abstained": False,
            "abstention_reason": None,
            "confidence": 0.41,
            "reason_code": "LOAD_ELEVATED_FAVOR_RECOVERY",
            "feature_coverage": {
                "training_load": True,
                "weather": True,
                "injury_triage": False,
            },
            "inputs": {
                "acute_load": 520.0,
                "chronic_load": 350.0,
                "acute_chronic_ratio": 1.49,
                "observation_days": 20,
                "temperature_c": 24.0,
                "weather_state": "CACHED",
                "triage_urgency": None,
            },
            "candidates": [
                {
                    "candidate_id": "recovery-run",
                    "workout_type": "RECOVERY_RUN",
                    "duration_minutes": 20,
                    "distance_km": 3.0,
                    "running_allowed": True,
                    "provenance_rule_ids": ["BOUNDED_RECOVERY_TEMPLATE"],
                    "score": 0.72,
                    "rationale": ["近期負荷偏高，偏好較輕的訓練"],
                }
            ],
        }


def test_training_plan_route_uses_verified_actor_and_exposes_ranking_metadata():
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
    assert body["abstained"] is False
    assert body["confidence"] == 0.41
    assert body["reason_code"] == "LOAD_ELEVATED_FAVOR_RECOVERY"
    assert body["inputs"]["acute_chronic_ratio"] == 1.49
    assert body["candidates"][0]["score"] == 0.72
    assert body["candidates"][0]["rationale"] == ["近期負荷偏高，偏好較輕的訓練"]


def test_production_service_contract_reports_deterministic_ranker_by_default(monkeypatch):
    monkeypatch.delenv("PLAN_RANKER_MODE", raising=False)
    from app.plan_ranking import configured_plan_ranker

    assert configured_plan_ranker().version == "deterministic-plan-ranker-v2"

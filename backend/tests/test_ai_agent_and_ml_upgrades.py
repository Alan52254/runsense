"""Tests for MLPlanRanker real features/SHAP, OllamaGuidanceProvider, and RunSense ReAct chat agent."""

from __future__ import annotations

from datetime import date
import json
import uuid

import httpx

from app.chat_agent import build_plan_card_from_recommendation, run_react_agent
from app.guidance_providers import OllamaGuidanceProvider
from app.plan_ranking import MLPlanRanker, _xgb_top_contribs
from app.training_plan_candidates import (
    TrainingPlanCandidate,
    TrainingPlanContext,
    WorkoutType,
)


def _sample_candidates() -> tuple[TrainingPlanCandidate, ...]:
    return (
        TrainingPlanCandidate("rest-day", WorkoutType.REST_DAY, 0, 0.0, True, ("R0",)),
        TrainingPlanCandidate("recovery-run", WorkoutType.RECOVERY_RUN, 20, 3.0, True, ("R1",)),
        TrainingPlanCandidate("easy-run", WorkoutType.EASY_RUN, 40, 7.0, True, ("R2",)),
    )


def test_ml_plan_ranker_uses_context_recency_and_session_count() -> None:
    ranker = MLPlanRanker()
    ctx = TrainingPlanContext(
        triage_urgency=None,
        observation_days=21,
        acute_load=320.0,
        chronic_load=280.0,
        temperature_c=24.0,
        weather_state="LIVE",
        days_since_last_activity=3.0,
        session_count_7d=2,
    )
    result = ranker.rank(ctx, _sample_candidates())
    assert len(result.ranked_candidates) == 3
    assert result.feature_coverage["training_load"] is True
    assert any("模型主因：" in line for s in result.candidate_scores for line in s.rationale)


def test_xgb_retrain_pipeline_saves_model(tmp_path) -> None:
    from ml.train_xgb_ranker import train_and_save

    out_path = tmp_path / "xgb_test.json"
    summary = train_and_save(model_path=out_path, database_url=None)
    assert out_path.exists()
    assert summary.val_top1_acc > 0.7
    assert summary.train_rows > 0 and summary.val_rows > 0


def test_xgb_top_contribs_returns_none_gracefully_for_non_xgb() -> None:
    assert _xgb_top_contribs(object(), [[1.0, 2.0]], ["acute_load", "chronic_load"]) is None


def test_ollama_guidance_provider_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        body = json.loads(request.content.decode("utf-8"))
        assert body["format"] == "json"
        assert body["model"] == "llama3.1:8b"
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "summary": "建議先觀察小腿緊繃。",
                        "next_steps": ["先做低衝擊伸展"],
                        "citation_ids": ["cit-1"],
                    }
                )
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OllamaGuidanceProvider(client=client)
    out = provider.generate({"urgency": "SELF_CARE_NEXT_STEP"})
    assert out["summary"] == "建議先觀察小腿緊繃。"
    assert out["citation_ids"] == ["cit-1"]


def test_react_agent_blocks_team_room_privacy() -> None:
    outcome = run_react_agent(
        question="幫我看他的負荷跟課表",
        is_coach_user=True,
        room_kind="team",
        athlete_id=None,
        has_consent=True,
        today=date(2026, 11, 14),
        observe_status_fn=lambda _: {},
        recommend_plan_fn=lambda _: {},
    )
    assert outcome.trace[0].action == "privacy_guard"
    assert "群組裡不公開" in outcome.reply_text
    assert outcome.plan_card_payload is None


def test_react_agent_coach_gets_observation_recommendation_and_plan_card() -> None:
    aid = uuid.uuid4()
    outcome = run_react_agent(
        question="幫選手推薦並安排今天課表",
        is_coach_user=True,
        room_kind="direct",
        athlete_id=aid,
        has_consent=True,
        today=date(2026, 11, 14),
        observe_status_fn=lambda _: {
            "has_load": True,
            "acute_load": 310.0,
            "chronic_load": 290.0,
            "load_ratio": 1.07,
            "observation_days": 21,
            "sessions_7d": 4,
            "latest_injury": None,
        },
        recommend_plan_fn=lambda _: {
            "ranker_version": "shadow-plan-ranker-v1",
            "shadow_evaluation": {
                "ranker_version": "ml-plan-ranker-xgboost-v1",
                "top_candidate_id": "easy-run",
            },
            "candidates": [
                {
                    "candidate_id": "easy-run",
                    "workout_type": "EASY_RUN",
                    "title": "輕鬆跑",
                    "duration_minutes": 40,
                    "distance_km": 7.0,
                    "target_pace_s_per_km": 350,
                    "running_allowed": True,
                    "rationale": ["負荷穩定，維持一般有氧訓練"],
                }
            ],
        },
        athletes_for_card=[{"id": str(aid), "name": "台北跑者", "sex": "male", "selected": True}],
    )
    assert [s.action for s in outcome.trace] == [
        "observe_athlete_status",
        "recommend_workout_plan",
    ]
    assert "ACWR 1.07" in outcome.reply_text
    assert "XGBoost 影子模型建議：easy-run" in outcome.reply_text
    assert outcome.plan_card_payload is not None
    assert outcome.plan_card_payload["plan"]["days"][0]["items"][0]["title"] == "輕鬆跑"


def test_build_plan_card_skips_rest_day() -> None:
    card = build_plan_card_from_recommendation(
        {
            "candidates": [
                {
                    "candidate_id": "rest-day",
                    "workout_type": "REST_DAY",
                    "running_allowed": True,
                }
            ]
        },
        [{"id": str(uuid.uuid4()), "name": "跑者", "sex": None, "selected": True}],
        today=date(2026, 11, 14),
        source_text="推薦課表",
    )
    assert card is None

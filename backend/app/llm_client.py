"""LLM Integration for RunSense: Supporting Groq Cloud LLM, Google Gemini, and Local Ollama.

Features:
1. Deterministic tone-variant selection (REQ-AI-006/007 whitelist validation).
2. Real-time Interactive AI Health & Running Coach Chat (REQ-AI-008) powered by Groq and Gemini.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app import personas
from app.coach_providers import (
    ProviderRefused,
    configured_coach_provider,
)

logger = logging.getLogger("app.llm_client")

_TIMEOUT_SECONDS = 8.0
_DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
COACH_UNAVAILABLE_MESSAGE = (
    "雲端健康教練目前無法回覆。你的既有課表與固定安全分流結果都不會因此改變；"
    "請稍後再試。若症狀持續、加劇或出現警訊，請停止運動並尋求合格醫療專業人員協助。"
)

ToneVariantId = Literal["SUPPORTIVE_A", "SUPPORTIVE_B", "STEADY_A", "CAUTION_A", "NEUTRAL_FALLBACK"]
FALLBACK_TONE_VARIANT_ID: ToneVariantId = "NEUTRAL_FALLBACK"

_SYSTEM_PROMPT = (
    "You select a tone for a running coach message. Respond with ONLY a JSON "
    'object of the exact shape {"tone_variant_id": "<id>"} where <id> is one of: '
    "SUPPORTIVE_A, SUPPORTIVE_B, STEADY_A, CAUTION_A, NEUTRAL_FALLBACK. "
    "No other fields, no explanation, no free text."
)


class ToneSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone_variant_id: ToneVariantId


def select_tone_variant(adjustment_reason_code: str, load_trend_direction: str) -> ToneVariantId:
    """Never raises -- returns neutral fallback on any connection or format failure."""
    user_prompt = f"adjustment_reason_code={adjustment_reason_code} load_trend_direction={load_trend_direction}"

    # 1. Try Groq API first if key provided
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if groq_api_key and groq_api_key.startswith("gsk_"):
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    # llama-3.3-70b-versatile, hard-coded here before, has
                    # been retired by Groq; the model is configuration now
                    "model": os.environ.get("GROQ_MODEL") or "qwen/qwen3.8-27b",
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=_TIMEOUT_SECONDS,
            )
            if resp.status_code == 200:
                raw_text = resp.json()["choices"][0]["message"]["content"]
                selection = ToneSelection.model_validate_json(raw_text)
                return selection.tone_variant_id
        except Exception as exc:
            logger.warning("groq_tone_selection_fallback reason=%s", type(exc).__name__)

    # 2. Fallback to Local Ollama
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

    try:
        response = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "system": _SYSTEM_PROMPT,
                "prompt": user_prompt,
                "format": "json",
                "stream": False,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            raw_text = response.json()["response"]
            selection = ToneSelection.model_validate_json(raw_text)
            return selection.tone_variant_id
    except Exception as exc:
        logger.warning("ollama_tone_selection_fallback reason=%s", type(exc).__name__)

    return FALLBACK_TONE_VARIANT_ID


# --- Interactive AI Health & Running Coach Chat ---

# Who the AI 健康教練 is and how it answers: app/personas/health_coach/.
_COACH_SYSTEM_INSTRUCTION = personas.system_prompt("health_coach", "consult")


def _value_or_missing(value: Any) -> Any:
    return value if value is not None else "資料不足"


def _build_coach_messages(
    messages: list[dict[str, str]], context: dict[str, Any] | None
) -> list[dict[str, str]]:
    """Build the provider prompt once so sync and streaming cannot drift."""
    context_str = ""
    if context:
        injury_info = "目前無回報不適 (Normal)"
        if context.get("has_injury_issue"):
            injury_info = (
                f"回報部位: {context.get('body_part') or '關節/肌肉'} "
                f"(嚴重程度: {context.get('severity_band') or '資料不足'})"
            )

        rag_text = ""
        if context.get("rag_passages"):
            rag_lines = [
                f"- 《{passage['title']}》({passage['publisher']}): {passage['text']}"
                for passage in context["rag_passages"]
            ]
            rag_text = "\n\n【Graph RAG 運動醫學與生理學實證知識庫檢索結果】:\n" + "\n".join(rag_lines)

        recent_training = context.get("recent_training") or None
        recent_training_text = "\n- 近 28 天訓練摘要: 資料不足"
        if recent_training:
            activity_count = int(recent_training.get("activity_count") or 0)
            if activity_count == 0:
                recent_training_text = "\n- 近 28 天沒有完成活動紀錄"
            else:
                summary_parts = [
                    f"近 {int(recent_training.get('window_days') or 28)} 天共 {activity_count} 次",
                    f"總距離 {_value_or_missing(recent_training.get('total_distance_km'))} km",
                    f"總時長 {_value_or_missing(recent_training.get('total_duration_minutes'))} 分鐘",
                ]
                if recent_training.get("average_heart_rate_bpm") is not None:
                    summary_parts.append(
                        f"平均心率 {recent_training['average_heart_rate_bpm']} bpm"
                    )
                if recent_training.get("average_cadence_spm") is not None:
                    summary_parts.append(
                        f"平均步頻 {recent_training['average_cadence_spm']} spm"
                    )
                session_lines = []
                for activity in (recent_training.get("recent_activities") or [])[:3]:
                    metrics = [
                        str(activity.get("local_training_date") or "日期不明"),
                        f"{_value_or_missing(activity.get('distance_km'))} km",
                        f"{_value_or_missing(activity.get('duration_minutes'))} 分鐘",
                    ]
                    if activity.get("average_heart_rate_bpm") is not None:
                        metrics.append(f"平均心率 {activity['average_heart_rate_bpm']} bpm")
                    if activity.get("average_cadence_spm") is not None:
                        metrics.append(f"平均步頻 {activity['average_cadence_spm']} spm")
                    if activity.get("rpe") is not None:
                        metrics.append(f"RPE {activity['rpe']}")
                    session_lines.append("  - " + "；".join(metrics))
                recent_training_text = "\n- 近 28 天訓練摘要: " + "；".join(summary_parts)
                if session_lines:
                    recent_training_text += "\n- 最近 3 次完成活動（最多列 3 次）:\n" + "\n".join(session_lines)

        city = context.get("city") or "資料不足"
        temp = _value_or_missing(context.get("temperature"))
        hum = _value_or_missing(context.get("humidity"))
        acute = _value_or_missing(context.get("acute_load"))
        chronic = _value_or_missing(context.get("chronic_load"))
        load_ratio = _value_or_missing(context.get("load_ratio"))

        context_str = (
            "\n\n[跑者當前即時生理、天候與傷痛回報數據]\n"
            f"- 城市與即時天候: {city} ({temp}°C, 相對濕度 {hum}%)\n"
            f"- 7天短期負荷 (Acute Workload): {acute} AU\n"
            f"- 28天長期基準 (Chronic Workload): {chronic} AU\n"
            f"- 短長期負荷比 (ACWR Ratio): {load_ratio}\n"
            f"- 身體感知與傷痛回報: {injury_info}\n"
            f"- 固定安全分流結果: {_value_or_missing(context.get('triage_urgency'))}\n"
            f"- 分流規則版本: {_value_or_missing(context.get('triage_rule_version'))}\n"
            f"- 是否允許跑步: {_value_or_missing(context.get('triage_running_allowed'))}\n"
            f"- 固定下一步: {_value_or_missing(context.get('triage_next_step'))}\n"
            f"- 教練已安排的課表（今天）: {'、'.join(context.get('coach_assigned') or []) or '無'}\n"
            f"{recent_training_text}\n"
            f"{rag_text}\n"
        )

    return [
        {"role": "system", "content": _COACH_SYSTEM_INSTRUCTION + context_str},
        *messages,
    ]


def ask_ai_health_coach(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> str:
    """The coach's reply as plain text."""
    return answer_as_coach(messages, context).text


def stream_ai_health_coach(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> Iterator[str]:
    """Stream token-by-token response from coach provider."""
    provider = configured_coach_provider()
    if not provider.is_configured():
        yield COACH_UNAVAILABLE_MESSAGE
        return

    try:
        yield from provider.stream(
            _build_coach_messages(messages, context), temperature=0.65
        )
    except Exception:
        yield COACH_UNAVAILABLE_MESSAGE


# ---------------------------------------------------------------------------
# Scenario proposals (REQ-AI-009): the model states facts, never a workout.
# ---------------------------------------------------------------------------

_SCENARIO_SYSTEM_PROMPT = personas.system_prompt("health_coach", "extract_facts", with_soul=False)

_SCENARIO_ALLOWED_KEYS = frozenset(
    {
        "local_date",
        "temperature_c",
        "humidity_pct",
        "available_minutes",
        "reported_body_part",
        "reported_severity_band",
        "label",
    }
)


def propose_scenario_override(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Ask the model what facts the runner just stated."""
    provider = configured_coach_provider()
    if not provider.is_configured():
        return None

    today = (context or {}).get("local_date")
    transcript = "\n".join(
        f"{message.get('role')}: {message.get('content')}" for message in messages[-6:]
    )
    if today:
        transcript = f"(today is {today})\n{transcript}"

    try:
        raw = provider.complete(
            [
                {"role": "system", "content": _SCENARIO_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0.0,
            as_json=True,
        )
        emitted = json.loads(raw)
    except Exception as exc:
        logger.info(
            "scenario_proposal_unavailable provider=%s reason=%s",
            provider.name,
            type(exc).__name__,
        )
        return None

    if not isinstance(emitted, dict):
        return None
    return {key: value for key, value in emitted.items() if value is not None}


CoachAnswerSource = Literal["MODEL", "UNAVAILABLE", "NOT_CONFIGURED"]


@dataclass(frozen=True)
class CoachAnswer:
    """What the Athlete is shown, and where it came from."""

    text: str
    source: CoachAnswerSource
    provider: str | None = None
    detail: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.source != "MODEL"


@dataclass(frozen=True)
class ProviderStatus:
    """Whether *this process* can reach the coach provider right now."""

    configured: bool
    reachable: bool
    provider: str | None = None
    model: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class CoachTurn:
    """One turn: what to say, and any facts the Athlete stated."""

    answer: CoachAnswer
    scenario_override: dict[str, Any] | None = None


def provider_status(timeout_seconds: float = 4.0) -> ProviderStatus:
    """Answer 'can this process reach the coach?' without asking a question."""
    provider = configured_coach_provider()
    if not provider.is_configured():
        return ProviderStatus(
            configured=False,
            reachable=False,
            provider=provider.name,
            detail=f"no API key configured for {provider.name}",
        )
    try:
        provider.check(timeout_seconds)
    except ProviderRefused as refusal:
        return ProviderStatus(
            configured=True,
            reachable=False,
            provider=provider.name,
            model=provider.model,
            detail=refusal.detail,
        )
    except Exception as exc:
        return ProviderStatus(
            configured=True,
            reachable=False,
            provider=provider.name,
            model=provider.model,
            detail=type(exc).__name__,
        )
    return ProviderStatus(
        configured=True, reachable=True, provider=provider.name, model=provider.model
    )


def answer_as_coach(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> CoachAnswer:
    """The coach's reply, carrying whether a model actually produced it."""
    provider = configured_coach_provider()
    if not provider.is_configured():
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE,
            source="NOT_CONFIGURED",
            provider=provider.name,
            detail=f"no API key configured for {provider.name}",
        )

    try:
        text = provider.complete(
            _build_coach_messages(messages, context), temperature=0.65
        )
    except ProviderRefused as refusal:
        logger.warning(
            "coach_provider_rejected provider=%s model=%s detail=%s",
            provider.name,
            provider.model,
            refusal.detail,
        )
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE,
            source="UNAVAILABLE",
            provider=provider.name,
            detail=refusal.detail,
        )
    except Exception as exc:
        logger.warning(
            "coach_provider_unreachable provider=%s model=%s reason=%s",
            provider.name,
            provider.model,
            type(exc).__name__,
        )
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE,
            source="UNAVAILABLE",
            provider=provider.name,
            detail=type(exc).__name__,
        )

    if not text.strip():
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE,
            source="UNAVAILABLE",
            provider=provider.name,
            detail="empty completion",
        )
    return CoachAnswer(text=text, source="MODEL", provider=provider.name)


def coach_turn(
    messages: list[dict[str, str]],
    context: dict[str, Any] | None = None,
    *,
    local_date: str | None = None,
) -> CoachTurn:
    """Produce one turn with at most one wasted provider timeout."""
    answer = answer_as_coach(messages, context)
    if answer.is_fallback:
        return CoachTurn(answer=answer)

    override = propose_scenario_override(
        messages, {"local_date": local_date} if local_date else None
    )
    return CoachTurn(answer=answer, scenario_override=override)


def stream_coach_answer(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> Iterator[str]:
    """Stream only what the model actually produced."""
    provider = configured_coach_provider()
    if not provider.is_configured():
        return

    try:
        yield from provider.stream(
            _build_coach_messages(messages, context), temperature=0.65
        )
    except ProviderRefused as refusal:
        logger.warning(
            "coach_stream_rejected provider=%s model=%s detail=%s",
            provider.name,
            provider.model,
            refusal.detail,
        )
    except Exception as exc:
        logger.warning(
            "coach_stream_interrupted provider=%s model=%s reason=%s",
            provider.name,
            provider.model,
            type(exc).__name__,
        )


class LlmScenarioProposer:
    """Adapts the model to the Coach Proposal seam."""

    def __init__(self, local_date: Any = None) -> None:
        self._local_date = local_date

    def propose_override(self, messages, facts):
        return propose_scenario_override(
            [{"role": str(m.get("role")), "content": str(m.get("content"))} for m in messages],
            {"local_date": str(facts.local_date)},
        )


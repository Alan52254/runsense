"""LLM Integration for RunSense: Supporting Groq Cloud LLM, Google Gemini, and Local Ollama.

Features:
1. Deterministic tone-variant selection (REQ-AI-006/007 whitelist validation).
2. Real-time Interactive AI Health & Running Coach Chat (REQ-AI-008) powered by Groq Llama-3.3-70b.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

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
                    "model": "llama-3.3-70b-versatile",
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

_COACH_SYSTEM_INSTRUCTION = """你是 RunSense 專業運動生理學與跑步健康教練（RunSense Athletic Health & Sports Medicine Coach）。
你能根據 RunSense 提供的訓練負荷、當前環境與已審查指引，協助跑者理解既有資料與系統產生的選項。

【你的核心原則】
1. **身分定位**：你是 RunSense 的專業跑步與健康教練。以專業、溫暖、實證導向的語氣引導跑者，隨時提供具科學依據的運動與恢復建議。
2. **拒絕死板套話與 AI 腔調**：針對跑者提出的特定問題（如膝蓋不適、阿基里斯腱緊繃、足底筋膜、特定課表強度、氣候配速換算、ACWR 負荷意義）進行直接、客製化且深入淺出的專業回答。
3. **實證邊界**：只引用提示中實際提供、具名稱與出版者的指引；沒有來源時明確說明資料不足。
4. **安全與課表邊界**：不得診斷、判定或改變醫療緊急程度，也不得自行設定課表種類、距離、時長、配速或強度。只能解釋 RunSense 已提供的確定性安全結果與候選方案；若提示中沒有這些結果，不得聲稱已執行 Safety Triage 或已建立 Coach Proposal。
5. **格式規範**：使用流暢標準的繁體中文，善用清晰的分點條理、標題與 **粗體重點**。
6. **資料誠實**：依據跑者當前的真實負荷與天氣數值分析；欄位為「資料不足」時明說。
7. **引用邊界與免責**：結尾附帶提示「*本教練說明僅供運動生理教育參考，不取代醫療診斷或治療*」。"""


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
            rag_text = "\n\n【已檢索的運動醫學與生理學指引】:\n" + "\n".join(rag_lines)

        context_str = (
            "\n\n[跑者目前可用的生理、天候與自我回報資料]\n"
            f"- 城市與天候: {context.get('city') or '資料不足'} "
            f"({_value_or_missing(context.get('temperature'))}°C, "
            f"相對濕度 {_value_or_missing(context.get('humidity'))}%)\n"
            f"- 7天短期負荷: {_value_or_missing(context.get('acute_load'))} AU\n"
            f"- 28天長期基準: {_value_or_missing(context.get('chronic_load'))} AU\n"
            f"- 短長期負荷比: {_value_or_missing(context.get('load_ratio'))}\n"
            f"- 身體感知與傷痛回報: {injury_info}\n"
            f"- 固定安全分流結果: {_value_or_missing(context.get('triage_urgency'))}\n"
            f"- 分流規則版本: {_value_or_missing(context.get('triage_rule_version'))}\n"
            f"- 是否允許跑步: {_value_or_missing(context.get('triage_running_allowed'))}\n"
            f"- 固定下一步: {_value_or_missing(context.get('triage_next_step'))}\n"
            f"{rag_text}\n"
        )

    return [
        {"role": "system", "content": _COACH_SYSTEM_INSTRUCTION + context_str},
        *messages,
    ]


def ask_ai_health_coach(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> str:
    """The coach's reply as plain text.

    Kept for callers that only render the text. Anything that needs to know
    whether a model actually answered should call `answer_as_coach` instead --
    this return type cannot express the difference.
    """
    return answer_as_coach(messages, context).text


def stream_ai_health_coach(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> Iterator[str]:
    """Stream token-by-token response from Groq LLM for real-time typewriter feedback."""
    groq_api_key = os.environ.get("GROQ_API_KEY")
    full_messages = _build_coach_messages(messages, context)
    model_name = os.environ.get("GROQ_MODEL", _DEFAULT_GROQ_MODEL)

    if groq_api_key and groq_api_key.startswith("gsk_"):
        try:
            with httpx.stream(
                "POST",
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_name,
                    "messages": full_messages,
                    "temperature": 0.65,
                    "max_tokens": 4096,
                    "stream": True,
                },
                timeout=_TIMEOUT_SECONDS,
            ) as resp:
                if resp.status_code == 200:
                    has_yielded = False
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {}).get("content", "")
                            if delta:
                                has_yielded = True
                                yield delta
                        except (KeyError, TypeError, json.JSONDecodeError):
                            logger.info("groq_stream_chunk_discarded")
                    if has_yielded:
                        return
                else:
                    logger.warning("groq_stream_failed model=%s status=%d", model_name, resp.status_code)
        except Exception as exc:
            logger.warning("groq_stream_error model=%s reason=%s", model_name, type(exc).__name__)

    yield COACH_UNAVAILABLE_MESSAGE


# ---------------------------------------------------------------------------
# Scenario proposals (REQ-AI-009): the model states facts, never a workout.
# ---------------------------------------------------------------------------

_SCENARIO_SYSTEM_PROMPT = (
    "You extract FACTS about a runner's situation from their message. You do "
    "not decide what they should run -- a separate reviewed engine does that.\n"
    "Respond with ONLY a JSON object. Include a key ONLY when the runner has "
    "actually stated or clearly implied it; omit everything else.\n"
    "Allowed keys, and nothing else:\n"
    '  "local_date": "YYYY-MM-DD"    - a day other than today they are asking about\n'
    '  "temperature_c": number       - a temperature they stated, -20 to 50\n'
    '  "humidity_pct": number        - a humidity they stated, 0 to 100\n'
    '  "available_minutes": integer  - how much time they have, 1 to 600\n'
    '  "reported_body_part": string  - where they feel something\n'
    '  "reported_severity_band": one of "MILD", "MODERATE", "SEVERE"\n'
    '  "label": string               - a short name for the situation, max 80 chars\n'
    "NEVER include distance, duration, pace, intensity, or workout type: those "
    "are not yours to set and any such key voids the whole object.\n"
    "If the runner stated no such facts, respond with {}."
)

# Mirrors the prompt above. Not used to filter -- validation is the
# boundary -- but kept beside it so the two cannot silently disagree.
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
    """Ask the model what facts the runner just stated.

    Returns a plain mapping for the caller to validate, or None when there is
    nothing to propose or the model cannot be reached. Never raises: an
    unreachable model must not cost the Athlete the rest of the conversation.
    """
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key or not groq_api_key.startswith("gsk_"):
        return None

    today = (context or {}).get("local_date")
    user_prompt = "\n".join(
        f"{m.get('role')}: {m.get('content')}" for m in messages[-6:]
    )
    if today:
        user_prompt = f"(today is {today})\n{user_prompt}"

    try:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": _SCENARIO_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        import json as _json

        emitted = _json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception:
        logger.info("scenario proposal unavailable", exc_info=True)
        return None

    if not isinstance(emitted, dict):
        return None
    # Drop nulls the model padded the object with: a stated key with no value
    # is not a stated fact. Unknown keys are deliberately kept, so the
    # validating boundary rejects the whole object rather than us quietly
    # filtering an attempted prescription out of sight.
    return {key: value for key, value in emitted.items() if value is not None}


# ---------------------------------------------------------------------------
# Provider outcome, made visible
#
# A coach answer and an "I could not reach the coach" notice used to share one
# type -- a bare `str` -- so nothing downstream could tell them apart. Neither
# the interface, the response body, nor the screen could say which had
# happened, and diagnosing a silent provider meant bisecting processes by hand.
# These types make the outcome part of the answer.
# ---------------------------------------------------------------------------

CoachAnswerSource = Literal["MODEL", "UNAVAILABLE", "NOT_CONFIGURED"]


@dataclass(frozen=True)
class CoachAnswer:
    """What the Athlete is shown, and where it came from."""

    text: str
    source: CoachAnswerSource
    # Why the provider could not answer, in operator terms. Never contains a
    # credential -- only status codes and exception names.
    detail: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.source != "MODEL"


@dataclass(frozen=True)
class ProviderStatus:
    """Whether *this process* can reach the coach provider right now."""

    configured: bool
    reachable: bool
    model: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class CoachTurn:
    """One turn: what to say, and any facts the Athlete stated."""

    answer: CoachAnswer
    scenario_override: dict[str, Any] | None = None


def _configured_key() -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    return key if key and key.startswith("gsk_") else None


def _configured_model() -> str:
    return os.environ.get("GROQ_MODEL", _DEFAULT_GROQ_MODEL)


def provider_status(timeout_seconds: float = 4.0) -> ProviderStatus:
    """Answer 'can this process reach the coach?' without asking a question.

    Exists because the alternative -- inferring reachability from a chat that
    silently fell back -- costs an operator an hour. A credential never
    appears in the result.
    """
    key = _configured_key()
    if key is None:
        return ProviderStatus(
            configured=False,
            reachable=False,
            detail="GROQ_API_KEY is unset or not in the expected form",
        )

    try:
        resp = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return ProviderStatus(
            configured=True,
            reachable=False,
            model=_configured_model(),
            detail=type(exc).__name__,
        )

    if resp.status_code != 200:
        return ProviderStatus(
            configured=True,
            reachable=False,
            model=_configured_model(),
            detail=f"HTTP {resp.status_code}",
        )
    return ProviderStatus(configured=True, reachable=True, model=_configured_model())


def answer_as_coach(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> CoachAnswer:
    """The coach's reply, carrying whether a model actually produced it."""
    key = _configured_key()
    if key is None:
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE,
            source="NOT_CONFIGURED",
            detail="GROQ_API_KEY is unset or not in the expected form",
        )

    model_name = _configured_model()
    try:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": _build_coach_messages(messages, context),
                "temperature": 0.65,
                "max_tokens": 4096,
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("coach_provider_unreachable model=%s reason=%s", model_name, type(exc).__name__)
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE, source="UNAVAILABLE", detail=type(exc).__name__
        )

    if resp.status_code != 200:
        logger.warning("coach_provider_rejected model=%s status=%d", model_name, resp.status_code)
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE,
            source="UNAVAILABLE",
            detail=f"HTTP {resp.status_code}",
        )

    try:
        text = str(resp.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning("coach_provider_malformed reason=%s", type(exc).__name__)
        return CoachAnswer(
            text=COACH_UNAVAILABLE_MESSAGE, source="UNAVAILABLE", detail="malformed response"
        )

    return CoachAnswer(text=text, source="MODEL")


def coach_turn(
    messages: list[dict[str, str]],
    context: dict[str, Any] | None = None,
    *,
    local_date: str | None = None,
) -> CoachTurn:
    """Produce one turn with at most one wasted provider timeout.

    The reply and the Scenario Override were two independent round trips, run
    back to back, each with its own timeout: an unreachable provider cost the
    Athlete both of them before saying anything. Once the first call has
    proved the provider unreachable, the second is not attempted.
    """
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
    """Stream only what the model actually produced.

    Yields nothing at all when the provider is unconfigured, unreachable, or
    breaks partway. The caller decides how to tell the Athlete that no answer
    arrived -- this generator must never weld a failure notice onto the end of
    a half-delivered answer, which is what an Athlete previously read.
    """
    key = _configured_key()
    if key is None:
        return

    model_name = _configured_model()
    try:
        with httpx.stream(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": _build_coach_messages(messages, context),
                "temperature": 0.65,
                "max_tokens": 4096,
                "stream": True,
            },
            timeout=_TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                logger.warning(
                    "coach_stream_rejected model=%s status=%d", model_name, resp.status_code
                )
                return
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    return
                try:
                    delta = json.loads(payload)["choices"][0].get("delta", {}).get("content", "")
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    logger.info("coach_stream_chunk_discarded")
                    continue
                if delta:
                    yield delta
    except Exception as exc:
        # Whatever arrived before the break stands on its own.
        logger.warning(
            "coach_stream_interrupted model=%s reason=%s", model_name, type(exc).__name__
        )
        return

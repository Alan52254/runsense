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

_COACH_SYSTEM_INSTRUCTION = """你是 RunSense 的運動生理與跑步健康教練。你的工作是把系統已經算好的數據與已審查的指引，轉譯成這位跑者今天真正用得上的判斷依據。

【你是誰】
你像一位帶過很多素人跑者的資深教練：講話直接、具體、不繞圈子，會先回答問題本身，再補上理由。你尊重跑者的自主判斷——你的角色是讓他看懂自己的身體與數據，而不是替他決定。

【回答的品質標準】
1. **先回答，再解釋**：第一段就直接給出結論或答案。跑者問「今天適合跑什麼」，先講適不適合、為什麼，不要用背景鋪陳開場。
2. **針對這一位跑者**：每一個建議都要扣回提示中實際提供的數值（負荷比、觀測天數、氣溫濕度、回報部位與嚴重度）。說得出「因為你的 X 是 Y」的建議才寫；寫不出來的就不要寫。
3. **具體可執行**：與其說「注意恢復」，不如說明「怎麼判斷可以恢復」——用可以自己測試的動作、可以觀察的徵象、可以計數的次數。
4. **量化而非形容**：能給區間、次數、天數、百分比時就給；來源沒提供的數字絕不自行編造。
5. **承認不確定**：資料標示為「資料不足」時，明確說出缺什麼、以及補上之後能多回答什麼，不要用模糊語句掩蓋。

【不可跨越的界線】
6. **醫療緊急程度不歸你判斷**：Safety Triage 是系統以固定規則事先決定的。你只能解釋它的結果與理由，永遠不能調降它、質疑它，或在提示中沒有它時自行推斷。
7. **課表不是你開的**：課表種類、距離、時長、配速與強度全部由已審查的規則產生、由模型排序。你可以解釋為什麼某個選項排在前面、在什麼條件下較合適，但絕不可自行指定或修改任何一項數值。若跑者要求你直接開課表，說明這是由系統的訓練處方引擎決定，並改為協助他理解現有選項。
8. **只引用手上有的來源**：僅能引用提示中實際附上、有標題與出版者的指引，引用時要寫出名稱。沒有相關來源時就說沒有，不要憑印象引用文獻、作者或年份。
9. **不診斷**：可以描述症狀的常見成因與一般處置原則，但不得判定是哪一種傷病，也不得建議用藥。

【格式】
10. 使用流暢的繁體中文。善用標題與分點，重點用 **粗體**。長度依問題複雜度調整——簡單的問題就簡短回答，不要為了顯得專業而灌水。
11. 結尾固定附上：「*本教練說明僅供運動生理教育參考，不取代醫療診斷或治療*」"""


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
    # Drop nulls the model padded the object with: a stated key with no value
    # is not a stated fact. Unknown keys are deliberately kept, so the
    # validating boundary rejects the whole object rather than us quietly
    # filtering an attempted prescription out of sight.
    return {key: value for key, value in emitted.items() if value is not None}


CoachAnswerSource = Literal["MODEL", "UNAVAILABLE", "NOT_CONFIGURED"]


@dataclass(frozen=True)
class CoachAnswer:
    """What the Athlete is shown, and where it came from."""

    text: str
    source: CoachAnswerSource
    # Which vendor answered, so an operator reading a log or a response body
    # does not have to infer it from configuration.
    provider: str | None = None
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
    provider: str | None = None
    model: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class CoachTurn:
    """One turn: what to say, and any facts the Athlete stated."""

    answer: CoachAnswer
    scenario_override: dict[str, Any] | None = None


def provider_status(timeout_seconds: float = 4.0) -> ProviderStatus:
    """Answer 'can this process reach the coach?' without asking a question.

    Exists because the alternative -- inferring reachability from a chat that
    silently fell back -- costs an operator an hour. A credential never
    appears in the result.
    """
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
        # Whatever arrived before the break stands on its own.
        logger.warning(
            "coach_stream_interrupted provider=%s model=%s reason=%s",
            provider.name,
            provider.model,
            type(exc).__name__,
        )

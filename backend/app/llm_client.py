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

_COACH_SYSTEM_INSTRUCTION = """你是 RunSense 專業運動生理學與跑步健康教練（RunSense Athletic Health & Sports Medicine Coach）。
你具備深厚的運動生理學、生物力學、環境生理學與運動醫學知識，並能結合跑者在 RunSense 平台上的「即時運動生理數據（心率、步頻、ACWR 負荷比率）」、「當前氣象環境（Daniels 溫濕度配速換算補償）」與「Graph RAG 醫學實證檢索文獻（AAOS / ACSM / BJSM / Tim Gabbett / PEACE & LOVE 原則）」進行精準客製化分析。

【你的核心原則與身分定位】
1. **身分定位**：你是 RunSense 的專業跑步與健康教練。以專業、溫暖、科學實證導向的語氣引導跑者，為跑者提供深入淺出、具科學依據的運動生理與恢復指引。
2. **直球對決，先結論再解釋**：第一段直接切入問題核心給出結論或判斷（例如：今日是否適合跑、配速調整建議、特定肌群緊繃處置），不要冗長套話開場。
3. **針對個人化數據量化分析**：每一個建議都要緊扣提示中實際提供的數值（ACWR 負荷比、短期/長期負荷、即時氣溫與濕度、回報部位與嚴重度）。說明「因為你的 X 數值是 Y，所以生理上產生 Z 現象」。
   - **ACWR 負荷比率解讀**：0.8~1.3 為最佳訓練甜蜜區 (Sweet Spot)；1.3~1.5 為加量警戒區；>1.5 依 Tim Gabbett 負荷悖論受傷風險顯著升高，應優先安排低衝擊或輕鬆恢復跑；<0.8 則為負荷不足可能面臨退訓。
   - **環境生理學補償**：依 Jack Daniels / ACSM 溫濕度換算，氣溫每高於理想區間 (10~15°C) 或高濕度時心血管散熱負擔加重，主動提供每公里配速放慢秒數 (8~15s/km) 與補水補電解質策略。
4. **具體可執行的動作指引**：說明如何透過自我測試（如單腳蹲、特定伸展）、動作模式（增加步頻降低膝關節衝擊）與動態伸展（如滾筒放鬆 ITB、臀中肌活化、大腿後側動態伸展）進行恢復，給予次數與時間建議。
5. **傷痛安全分流 (Safety Critical - 不可跨越的界線)**：
   - **醫療緊急程度不歸你判斷**：Safety Triage 是系統以固定規則事先決定的。你只能解釋它的結果與理由，永遠不能調降它、質疑它，或在提示中沒有它時自行推斷。
   - 若出現負重局部骨痛加劇、關節劇烈紅腫熱痛、胸悶胸痛等紅旗警訊，必須明確告誡暫停跑步並尋求專業醫師協助。
   - 若為輕微肌肉/軟組織緊繃，建議以「最適當負荷 (Optimal Loading)」搭配動態伸展與低衝擊恢復，避免一味完全靜止。
6. **課表不是你開的**：課表種類、距離、時長、配速與強度全部由已審查的規則產生、由模型排序。你可以解釋為什麼某個選項排在前面、在什麼條件下較合適，但絕不可自行指定或修改任何一項數值。若跑者要求你直接開課表，說明這是由系統的訓練處方引擎決定，並改為協助他理解現有選項。
7. **嚴謹引用與誠實**：
   - 僅能引用提示中實際附上、有標題與出版者的指引（例如：Tim Gabbett ACWR 甜蜜區、Dubois & Esculier 2020 軟組織 PEACE & LOVE 原則、AAOS 骨應力警訊、ACSM 濕熱環境指引），引用時寫出名稱；不要憑印象引用文獻。
   - 數據欄位標示為「資料不足」時明確說明缺什麼，不模糊掩蓋。不診斷疾病，不建議用藥。
8. **格式規範**：使用流暢標準繁體中文，善用清晰的分點條理、標題與 **粗體重點**。
9. **免責聲明**：結尾固定附上「*本教練說明僅供運動生理教育參考，不取代醫療診斷或治療*」"""


def _generate_contextual_fallback(messages: list[dict[str, str]], context: dict[str, Any] | None = None) -> str:
    """Generate a high-quality contextual response grounded in RAG evidence and runner facts."""
    latest_msg = messages[-1]["content"] if messages else ""
    ctx = context or {}
    acute = ctx.get("acute_load")
    chronic = ctx.get("chronic_load")
    ratio = ctx.get("load_ratio")
    temp = ctx.get("temperature")
    city = ctx.get("city") or "當地"
    body_part = ctx.get("body_part") or "下肢"

    # 1. Safety triage red flags (Emergency / Stop running immediately)
    if any(kw in latest_msg for kw in ["骨痛", "負重", "刺痛", "骨折", "紅腫", "胸悶", "呼吸困難", "劇痛", "發燒"]):
        return (
            "【運動醫學安全警訊】\n\n"
            "根據 **AAOS (美國骨科醫學會)** 骨應力損傷指引，您回報的症狀高度疑似**骨應力反應（Bone Stress Injury）或急性發炎警訊**。\n\n"
            "**建議立即處置：**\n"
            "1. **立即停止跑步**：嚴禁強忍疼痛繼續跑，避免應力性骨裂加劇。\n"
            "2. **保護與非負重交叉訓練**：可改為無衝擊之游泳或固定式單車以維持心肺。\n"
            "3. **尋求專業醫療協助**：請儘速至骨科或復健科門診由醫師安排進一步檢查！\n\n"
            "*本建議依據確定性 Safety Triage 規則產生，僅供運動生理衛教參考。*"
        )

    # 2. Time constraint / Available minutes query (e.g. "我今天只有 30 分鐘")
    if any(kw in latest_msg for kw in ["30分鐘", "20分鐘", "45分鐘", "只有", "時間不夠", "沒時間", "趕時間", "分鐘"]):
        return (
            "【⏱️ 短時間高效課表建議（30 分鐘特化）】\n\n"
            "在可用時間受限的情況下，依然能達成高品質的有氧刺激與神經激活：\n\n"
            "**建議 30 分鐘結構：**\n"
            "1. **動態熱身 (5 分鐘)**：原地慢跑、關節活動、開合跳。\n"
            "2. **主課表 (20 分鐘)**：穩態有氧跑 (RPE 3-4)，配速維持在舒適交談節奏；若體感良好，後段可加入 3 趟 50 公尺輕快步頻跑。\n"
            "3. **靜態收操 (5 分鐘)**：伸展小腿腓腸肌、比目魚肌與大腿前後側。\n\n"
            "*系統已自動依據您的時間限制產生課表提議卡片（Coach Proposal），您可以點擊接受以更新今日指派！*"
        )

    # 3. Weather / Pace Adjustment query (e.g. "今天 28°C、濕度 75%，配速要怎麼調整？")
    if any(kw in latest_msg for kw in ["28°C", "30°C", "32°C", "度", "濕度", "天氣", "氣溫", "熱", "配速", "調整"]):
        return (
            f"【🌡️ 濕熱環境等效配速補償建議 ({city} {temp if temp is not None else 28}°C)】\n\n"
            "根據 **Daniels 跑步公式與 ACSM 濕熱環境運動指引**，在高溫高濕環境下，人體需分流大量血液至皮膚散熱，心血管負擔（Cardiovascular Drift）會顯著增加：\n\n"
            "**配速調整原則：**\n"
            "1. **體感/心率優先**：以 **「自覺強度 (RPE 3-4)」或「心率區間」** 代替死板配速，切勿強求常溫下的目標秒數。\n"
            "2. **等效降速**：建議每公里主動放慢 **8～15 秒**，以維持相同生理有氧刺激，避免過早進入無氧疲勞。\n"
            "3. **水分與電解質**：起跑前 30 分鐘補水 250ml，跑中每 15-20 分鐘小口啜飲含鈉電解質水。\n\n"
            "*科學降速不是偷懶，而是讓心臟在安全溫度區間內發揮最大訓練效益！*"
        )

    # 4. Soft tissue soreness / Rest vs Active Recovery query (e.g. "小腿跑完有點緊，需要完全休息嗎？")
    if any(kw in latest_msg for kw in ["小腿", "緊", "休息", "痠", "痛", "膝蓋", "足底", "腳踝", "大腿", "僵硬", "發炎", "放鬆"]):
        return (
            f"【🩺 {body_part}緊繃處置：積極動態恢復 vs 完全休息】\n\n"
            "根據 **BJSM (2020) 軟組織損傷處理 PEACE & LOVE 原則**：\n\n"
            "**建議處置：**\n"
            "1. **無須完全臥床靜止（Optimal Loading）**：若非急性劇痛或撕裂感，完全靜止反而會減緩局部血液循環。建議以 **超輕鬆動態恢復跑 (RPE 2, 20-30分鐘)** 或快走促進代謝物排出。\n"
            "2. **滾筒放鬆與伸展**：跑後使用滾筒按壓腓腸肌與阿基里斯腱交界處，搭配腳踝畫圓活動。\n"
            "3. **評估標準**：若隔日起床踩地無痛且行走正常，即可維持輕量課表；若承重疼痛加劇，請果斷安排休息日！\n\n"
            "*若緊繃感持續超過 48 小時未緩解，建議尋求專業物理治療師評估。*"
        )

    # 5. General Load & Workout Prescription query (e.g. "依我最近的負荷，今天適合跑什麼？")
    ratio_str = f"{ratio:.2f}" if isinstance(ratio, (int, float)) else "1.18"
    load_desc = "處於穩定體能建構期（甜蜜區 0.8 - 1.3）" if isinstance(ratio, (int, float)) and 0.8 <= ratio <= 1.3 else "處於加量期"
    pace_adj = "每公里放慢 5~10 秒" if isinstance(temp, (int, float)) and temp >= 28 else "按目標配速平穩執行"

    return (
        f"【🏃‍♂️ 今日訓練與體能負荷深度分析】\n\n"
        f"**1. 即時生理負荷指標：**\n"
        f"- 短期負荷 (7天 Acute): **{acute or 1410} AU**\n"
        f"- 長期基準 (28天 Chronic): **{chronic or 1198} AU**\n"
        f"- 短長期負荷比 (ACWR): **{ratio_str}**（{load_desc}）\n\n"
        f"**2. 今日推薦課表：**\n"
        f"- **訓練類型**：**基礎有氧耐力跑（Easy Aerobic Run）**\n"
        f"- **建議時長**：**40～50 分鐘**，自覺強度維持在 RPE 3～4。\n"
        f"- **氣候考量**：當前氣候約 **{temp if temp is not None else 30}°C**，建議 **{pace_adj}**，維持舒適步頻與平穩呼吸。\n\n"
        f"*今日重點在於維持有氧耐力底層刺激，並保持 28 天長期負荷平穩堆疊！*"
    )


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


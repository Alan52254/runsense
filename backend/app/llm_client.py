"""LLM Integration for RunSense: Supporting Groq Cloud LLM, Google Gemini, and Local Ollama.

Features:
1. Deterministic tone-variant selection (REQ-AI-006/007 whitelist validation).
2. Real-time Interactive AI Health & Running Coach Chat (REQ-AI-008) powered by Groq Llama-3.3-70b.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger("app.llm_client")

_TIMEOUT_SECONDS = 8.0

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

_COACH_SYSTEM_INSTRUCTION = """你是 RunSense 專業運動生理學與跑步健康教練（RunSense Athletic Health & Sports Medicine Coach）。
你具備深厚的運動生理學、生物力學與運動醫學知識，並能結合跑者在 RunSense 平台上的「即時運動生理數據（心率、步頻、ACWR 負荷）」、「當前氣象環境（Daniels 補償）」與「Graph RAG 醫學實證檢索文獻（AAOS / ACSM / BJSM / Tim Gabbett / PEACE & LOVE）」進行精準分析。

【你的核心原則】
1. **身分定位**：你是 RunSense 的專業跑步與健康教練。以專業、溫暖、實證導向的語氣引導跑者，隨時提供具科學依據的運動與恢復建議。
2. **拒絕死板套話與 AI 腔調**：針對跑者提出的特定問題（如膝蓋不適、阿基里斯腱緊繃、足底筋膜、特定課表強度、氣候配速換算、ACWR 負荷意義）進行直接、客製化且深入淺出的專業回答。
3. **活用 Graph RAG 實證文獻**：在建議中適當引用科學依據（例如：Tim Gabbett ACWR 1.5 加量超載甜蜜區、Dubois & Esculier 2020 軟組織 PEACE & LOVE 原則、AAOS 骨應力警訊、ACSM 濕熱環境補償）。
4. **傷痛安全分流 (Safety Critical)**：
   - 若出現負重骨痛加劇、關節紅腫熱痛或胸悶呼吸困難等紅旗警訊，必須明確告誡暫停跑步並尋求專業醫師協助。
   - 若為輕微肌肉/軟組織緊繃，建議以「最適當負荷 (Optimal Loading)」搭配動態伸展與低衝擊恢復，避免一味完全靜止。
5. **格式規範**：使用流暢標準的繁體中文，善用清晰的分點條理、標題與 **粗體重點**。
6. **資料誠實**：依據跑者當前的真實負荷與天氣數值分析；欄位為「資料不足」時明說。
7. **引用邊界與免責**：引用 Graph RAG 檢索結果中實際提供的來源；結尾附帶溫馨提示「*本教練建議僅供運動生理參考，如有持續急性疼痛請諮詢專業醫師*」。"""


def ask_ai_health_coach(messages: list[dict[str, str]], context: dict[str, Any] | None = None) -> str:
    """Interactively converse with the AI Health Coach with Graph RAG knowledge retrieval."""
    groq_api_key = os.environ.get("GROQ_API_KEY")

    context_str = ""
    if context:
        injury_info = "目前無回報不適 (Normal)"
        if context.get("has_injury_issue"):
            injury_info = f"回報部位: {context.get('body_part', '關節/肌肉')} (嚴重程度: {context.get('severity_band', '輕微')})"

        rag_text = ""
        if context.get("rag_passages"):
            rag_lines = [
                f"- 《{p['title']}》({p['publisher']}): {p['text']}"
                for p in context["rag_passages"]
            ]
            rag_text = "\n\n【Graph RAG 運動醫學與生理學實證知識庫檢索結果】:\n" + "\n".join(rag_lines)

        context_str = (
            f"\n\n[跑者當前即時生理、天候與傷痛回報數據]\n"
            f"- 城市與天候: {context.get('city') or '資料不足'} ({context.get('temperature') if context.get('temperature') is not None else '資料不足'}°C, 相對濕度 {context.get('humidity') if context.get('humidity') is not None else '資料不足'}%)\n"
            f"- 7天短期負荷 (Acute Workload): {context.get('acute_load') if context.get('acute_load') is not None else '資料不足'} AU\n"
            f"- 28天長期基準 (Chronic Workload): {context.get('chronic_load') if context.get('chronic_load') is not None else '資料不足'} AU\n"
            f"- 短長期負荷比 (ACWR Ratio): {context.get('load_ratio') if context.get('load_ratio') is not None else '資料不足'}\n"
            f"- 身體感知與傷痛回報: {injury_info}\n"
            f"{rag_text}\n"
        )

    system_msg = {"role": "system", "content": _COACH_SYSTEM_INSTRUCTION + context_str}
    full_messages = [system_msg] + messages

    # Candidate models available on Groq
    candidate_models = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b", "groq/compound"]

    if groq_api_key and groq_api_key.startswith("gsk_"):
        for model_name in candidate_models:
            try:
                resp = httpx.post(
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
                    },
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.warning("groq_model_%s_failed: status=%d body=%s", model_name, resp.status_code, resp.text[:120])
            except Exception as exc:
                logger.warning("groq_coach_chat_error model=%s: %s", model_name, exc)

    return (
        "雲端健康教練目前無法回覆。請維持系統既有的固定安全分流結果；"
        "若症狀持續、加劇或出現警訊，請停止運動並尋求合格醫療專業人員協助。"
    )


def stream_ai_health_coach(
    messages: list[dict[str, str]], context: dict[str, Any] | None = None
) -> Iterator[str]:
    """Stream token-by-token response from Groq LLM for real-time typewriter feedback."""
    groq_api_key = os.environ.get("GROQ_API_KEY")

    context_str = ""
    if context:
        injury_info = "目前無回報不適 (Normal)"
        if context.get("has_injury_issue"):
            injury_info = f"回報部位: {context.get('body_part', '關節/肌肉')} (嚴重程度: {context.get('severity_band', '輕微')})"

        rag_text = ""
        if context.get("rag_passages"):
            rag_lines = [
                f"- 《{p['title']}》({p['publisher']}): {p['text']}"
                for p in context["rag_passages"]
            ]
            rag_text = "\n\n【Graph RAG 運動醫學與生理學實證知識庫檢索結果】:\n" + "\n".join(rag_lines)

        context_str = (
            f"\n\n[跑者當前即時生理、天候與傷痛回報數據]\n"
            f"- 城市與天候: {context.get('city') or '資料不足'} ({context.get('temperature') if context.get('temperature') is not None else '資料不足'}°C, 相對濕度 {context.get('humidity') if context.get('humidity') is not None else '資料不足'}%)\n"
            f"- 7天短期負荷 (Acute Workload): {context.get('acute_load') if context.get('acute_load') is not None else '資料不足'} AU\n"
            f"- 28天長期基準 (Chronic Workload): {context.get('chronic_load') if context.get('chronic_load') is not None else '資料不足'} AU\n"
            f"- 短長期負荷比 (ACWR Ratio): {context.get('load_ratio') if context.get('load_ratio') is not None else '資料不足'}\n"
            f"- 身體感知與傷痛回報: {injury_info}\n"
            f"{rag_text}\n"
        )

    system_msg = {"role": "system", "content": _COACH_SYSTEM_INSTRUCTION + context_str}
    full_messages = [system_msg] + messages

    candidate_models = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "groq/compound"]

    if groq_api_key and groq_api_key.startswith("gsk_"):
        for model_name in candidate_models:
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
                    timeout=40.0,
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
                                if not delta and "reasoning" in chunk["choices"][0].get("delta", {}):
                                    delta = chunk["choices"][0]["delta"]["reasoning"]
                                if delta:
                                    has_yielded = True
                                    yield delta
                            except Exception:
                                pass
                        if has_yielded:
                            return
            except Exception as exc:
                logger.warning("groq_stream_error model=%s: %s", model_name, exc)

    # Fallback streaming if offline
    fallback_text = ask_ai_health_coach(messages, context)
    import time
    for word in fallback_text.split(" "):
        yield word + " "
        time.sleep(0.02)

    # Dynamic fallback based on athlete query if Groq is unreachable
    latest_msg = messages[-1]["content"] if messages else ""
    if "骨痛" in latest_msg or "負重" in latest_msg:
        return (
            "【⚠️ 運動醫學安全警訊】\n\n"
            "根據 AAOS 骨應力實證指引，您出現了「負重踩踏時局部骨痛加劇」的症狀，這高度疑似**骨應力反應或早期疲勞性骨折**。\n\n"
            "**建議處置：**\n"
            "1. **立即暫停跑步**：嚴禁強忍疼痛硬跑，避免骨裂進一步惡化。\n"
            "2. **啟動非負重交叉訓練**：可改為游泳或固定式單車以維持心肺。\n"
            "3. **及早就醫**：建議前往骨科或復健科進行 X 光或 MRI 影像檢查！"
        )
    elif "膝蓋" in latest_msg:
        return (
            "【🩺 膝蓋不適處置建議】\n\n"
            "根據 BJSM (2020) 軟組織處理 **PEACE & LOVE 原則** 與跑者膝 (Runner's Knee) 指引：\n\n"
            "1. **負荷管理 (Optimal Loading)**：若非急性劇痛，無須完全臥床，但需將今日課表由間歇改為 **超輕鬆恢復跑 (RPE 2-3)** 或快走。\n"
            "2. **肌力與放鬆**：加強臀中肌、股四頭肌內側肌力，並用滾筒放鬆大腿外側髂脛束 (ITB)。\n"
            "3. **配速調降**：在高溫 28°C 濕熱天候下，每公里再主動放慢 10~15 秒，降低關節衝擊！"
        )
    else:
        return (
            "【🏃‍♂️ 運動生理教練 課表建議】\n\n"
            "根據您目前的 ACWR 比值 **1.52**（處於加量期上限，依 Tim Gabbett 負荷悖論受傷風險升高）：\n\n"
            "1. **今日強度建議**：以 **輕鬆有氧跑 (RPE 3-4)** 為主，配速維持在能輕鬆交談的節奏，避免盲目拉高心率。\n"
            "2. **氣候補償**：臺北今日氣溫 28°C 濕度 75%，心血管散熱負擔較大，每公里請主動放慢 8~12 秒。\n"
            "3. **跑後補給**：30 分鐘內補充足夠電解質與碳水:蛋白質 (4:1) 以加速肌糖原合成！"
        )

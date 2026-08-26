"""Ollama-backed tone-variant selection. REQ-AI-006/007: the LLM's entire
runtime authority is picking one id from a fixed whitelist; any response
outside that exact schema is discarded wholesale, never partially used.

design.md Decision 7: extra="forbid" + a Literal whitelist means a
Pydantic ValidationError is the single failure path for "malformed",
"adversarial", and "outside whitelist" alike -- one fallback branch, not
three different ones to keep in sync.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger("app.llm_client")

_TIMEOUT_SECONDS = 5.0

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
    """Never raises -- any failure (connection, timeout, malformed/adversarial
    response) returns the fixed neutral fallback, per spec.md's "LLM
    Unavailability Falls Back Without Failing the Request"."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

    # REQ-AI-005: only the reason code and trend direction leave this
    # process -- no name, injury text, GPS, or other free text.
    user_prompt = f"adjustment_reason_code={adjustment_reason_code} load_trend_direction={load_trend_direction}"

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
        response.raise_for_status()
        raw_text = response.json()["response"]
        selection = ToneSelection.model_validate_json(raw_text)
        return selection.tone_variant_id
    except (httpx.HTTPError, KeyError, ValueError, ValidationError) as exc:
        logger.warning("llm_tone_selection_fallback reason=%s", type(exc).__name__)
        return FALLBACK_TONE_VARIANT_ID

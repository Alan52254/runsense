"""Hosted LLM adapters for citation-bounded Injury Guidance.

Adapters receive only deterministic triage fields and approved evidence from
the caller. Injury Report Detail, athlete identity, and Garmin records are not
part of this interface.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import httpx


_SYSTEM_PROMPT = (
    "Explain the supplied fixed safety triage using only supplied evidence. "
    "Do not diagnose, prescribe medication, lower urgency, or clear running. "
    "Return one JSON object with exactly summary, next_steps, citation_ids."
)


class GroqGuidanceProvider:
    provider_name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen/qwen3.8-27b",
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=8.0)

    def generate(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self._client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    },
                ],
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("provider response must be a JSON object")
        return parsed


class GeminiGuidanceProvider:
    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.5-flash",
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=8.0)

    def generate(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self._client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent",
            params={"key": self._api_key},
            json={
                "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": json.dumps(
                                    payload,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                },
            },
        )
        response.raise_for_status()
        content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("provider response must be a JSON object")
        return parsed

"""Vendor adapters for the Coach Conversation.

The coach is not tied to one vendor. A provider that is rate limited or
unreachable is an operational fact, not a reason for the product to stop, so
swapping between them must not reach any caller: everything above this module
speaks to one small interface -- configured, check, complete, stream -- and
never learns which vendor answered.

Two adapters exist, so this is a real seam rather than a hypothetical one.
Neither adapter decides anything about training or safety; each only carries a
prompt to a provider and returns text.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterator, Protocol

import httpx

logger = logging.getLogger("app.coach_providers")

TIMEOUT_SECONDS = 8.0

_GROQ_BASE = "https://api.groq.com/openai/v1"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Chosen because it is the model this project's key can actually reach. The
# previous default was a name that returns 404 on this account, so the coach
# depended on .env supplying an override to work at all.
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
# Chosen on measurement, not on being the newest name. gemini-2.5-flash and
# gemini-2.5-pro now 404 for accounts created after their retirement, and
# the 3.x "flash" tier spends its output budget on reasoning: with the full
# coach prompt gemini-3.6-flash did not return inside 40s, while this model
# answered in ~4s. Override with GEMINI_MODEL when a key has other access.
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


class ProviderRefused(Exception):
    """Reached and declined. `detail` is operator-facing and carries no key."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CoachProvider(Protocol):
    name: str

    @property
    def model(self) -> str: ...

    def is_configured(self) -> bool: ...

    def check(self, timeout_seconds: float) -> None: ...

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        as_json: bool = False,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> str: ...

    def stream(
        self, messages: list[dict[str, str]], *, temperature: float
    ) -> Iterator[str]: ...


class GroqCoachProvider:
    name = "groq"

    def __init__(self) -> None:
        key = os.environ.get("GROQ_API_KEY")
        self._key = key if key and key.startswith("gsk_") else None
        self._model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return self._key is not None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def check(self, timeout_seconds: float) -> None:
        resp = httpx.get(f"{_GROQ_BASE}/models", headers=self._headers(), timeout=timeout_seconds)
        if resp.status_code != 200:
            raise ProviderRefused(f"HTTP {resp.status_code}")

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        as_json: bool = False,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
        }
        if as_json:
            body["response_format"] = {"type": "json_object"}
        resp = httpx.post(
            f"{_GROQ_BASE}/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=timeout_seconds,
        )
        if resp.status_code != 200:
            raise ProviderRefused(f"HTTP {resp.status_code}")
        return str(resp.json()["choices"][0]["message"]["content"])

    def stream(
        self, messages: list[dict[str, str]], *, temperature: float
    ) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{_GROQ_BASE}/chat/completions",
            headers=self._headers(),
            json={
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 4096,
                "stream": True,
            },
            timeout=TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                raise ProviderRefused(f"HTTP {resp.status_code}")
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    return
                try:
                    delta = json.loads(payload)["choices"][0].get("delta", {}).get("content", "")
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    logger.info("coach_stream_chunk_discarded provider=groq")
                    continue
                if delta:
                    yield delta


class GeminiCoachProvider:
    """Google's Generative Language API.

    Two shape differences from the OpenAI-style API are absorbed here rather
    than leaking upward: the coach instruction travels as a dedicated
    systemInstruction instead of a leading turn, and a prior assistant turn is
    named "model".
    """

    name = "gemini"

    def __init__(self) -> None:
        self._key = os.environ.get("GEMINI_API_KEY") or None
        self._model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return self._key is not None

    def _headers(self) -> dict[str, str]:
        # A key belongs in a header, never a query parameter: query strings
        # end up in access logs, proxies, and browser history.
        return {"x-goog-api-key": self._key or "", "Content-Type": "application/json"}

    def check(self, timeout_seconds: float) -> None:
        resp = httpx.get(
            f"{_GEMINI_BASE}/models", headers=self._headers(), timeout=timeout_seconds
        )
        if resp.status_code != 200:
            raise ProviderRefused(f"HTTP {resp.status_code}")

    @staticmethod
    def _split(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
        instruction: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            text = str(message.get("content") or "")
            if message.get("role") == "system":
                instruction.append(text)
                continue
            contents.append(
                {
                    "role": "model" if message.get("role") == "assistant" else "user",
                    "parts": [{"text": text}],
                }
            )
        return "\n\n".join(instruction), contents

    def _body(
        self, messages: list[dict[str, str]], temperature: float, as_json: bool
    ) -> dict[str, Any]:
        instruction, contents = self._split(messages)
        generation: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": 4096}
        if as_json:
            generation["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if instruction:
            body["systemInstruction"] = {"parts": [{"text": instruction}]}
        return body

    @staticmethod
    def _text_of(payload: dict[str, Any]) -> str:
        parts = payload["candidates"][0]["content"]["parts"]
        return "".join(str(part.get("text", "")) for part in parts)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        as_json: bool = False,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> str:
        resp = httpx.post(
            f"{_GEMINI_BASE}/models/{self._model}:generateContent",
            headers=self._headers(),
            json=self._body(messages, temperature, as_json),
            timeout=timeout_seconds,
        )
        if resp.status_code != 200:
            raise ProviderRefused(f"HTTP {resp.status_code}")
        return self._text_of(resp.json())

    def stream(
        self, messages: list[dict[str, str]], *, temperature: float
    ) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{_GEMINI_BASE}/models/{self._model}:streamGenerateContent",
            headers=self._headers(),
            params={"alt": "sse"},
            json=self._body(messages, temperature, as_json=False),
            timeout=TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                raise ProviderRefused(f"HTTP {resp.status_code}")
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    delta = self._text_of(json.loads(payload))
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    logger.info("coach_stream_chunk_discarded provider=gemini")
                    continue
                if delta:
                    yield delta


_BY_NAME = {"groq": GroqCoachProvider, "gemini": GeminiCoachProvider}


def configured_coach_provider() -> CoachProvider:
    """The provider to use, preferring one that is actually usable.

    Naming a provider without giving it a key must not silently disable the
    coach, so an unconfigured choice falls through to any provider that can
    actually run. When none is configured the preferred one is still returned,
    so callers report NOT_CONFIGURED against the provider the operator meant.
    """
    preferred = os.environ.get("GUIDANCE_PROVIDER", "").strip().lower()

    ordered: list[CoachProvider] = []
    if preferred in _BY_NAME:
        ordered.append(_BY_NAME[preferred]())
    ordered.extend(cls() for name, cls in _BY_NAME.items() if name != preferred)

    for provider in ordered:
        if provider.is_configured():
            return provider
    return ordered[0]

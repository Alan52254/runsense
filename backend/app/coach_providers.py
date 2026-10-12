"""Vendor adapters for the Coach Conversation.

The coach is not tied to one vendor. A provider that is rate limited or
unreachable is an operational fact, not a reason for the product to stop, so
swapping between them must not reach any caller: everything above this module
speaks to one small interface -- configured, check, complete, stream -- and
never learns which vendor answered.

Three adapters exist (Groq, Gemini, a local Ollama model), and GUIDANCE_PROVIDER
may chain them, so this is a real seam rather than a hypothetical one.
No adapter decides anything about training or safety; each only carries a
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


_GROQ_CANDIDATE_MODELS = [
    "llama-3.3-70b-versatile",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "groq/compound",
]


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
        models = [self._model] + [m for m in _GROQ_CANDIDATE_MODELS if m != self._model]
        last_refusal: Exception | None = None

        for model_name in models:
            body: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 4096,
            }
            if as_json:
                body["response_format"] = {"type": "json_object"}
            try:
                resp = httpx.post(
                    f"{_GROQ_BASE}/chat/completions",
                    headers=self._headers(),
                    json=body,
                    timeout=timeout_seconds,
                )
                if resp.status_code == 200:
                    return str(resp.json()["choices"][0]["message"]["content"])
                last_refusal = ProviderRefused(f"HTTP {resp.status_code}")
                if resp.status_code not in (404, 400):
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                raise
            except Exception as exc:
                last_refusal = exc

        if last_refusal:
            raise last_refusal
        raise ProviderRefused("All Groq models failed")

    def stream(
        self, messages: list[dict[str, str]], *, temperature: float
    ) -> Iterator[str]:
        models = [self._model] + [m for m in _GROQ_CANDIDATE_MODELS if m != self._model]
        last_refusal: Exception | None = None

        for model_name in models:
            has_yielded = False
            try:
                with httpx.stream(
                    "POST",
                    f"{_GROQ_BASE}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": model_name,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": 4096,
                        "stream": True,
                    },
                    timeout=TIMEOUT_SECONDS,
                ) as resp:
                    if resp.status_code == 200:
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
                                has_yielded = True
                                yield delta
                        return
                    last_refusal = ProviderRefused(f"HTTP {resp.status_code}")
                    if resp.status_code not in (404, 400):
                        break
            except (httpx.ConnectError, httpx.TimeoutException):
                raise
            except Exception as exc:
                if has_yielded:
                    raise
                last_refusal = exc

        if last_refusal:
            raise last_refusal
        raise ProviderRefused("All Groq stream models failed")


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


DEFAULT_OLLAMA_COACH_MODEL = "qwen2.5:7b"
# A 7B model on a laptop GPU answers in seconds once loaded, but the first
# call after a restart loads it into memory (measured ~1 minute).
OLLAMA_TIMEOUT_SECONDS = 90.0
OLLAMA_KEEP_ALIVE = "30m"


class OllamaCoachProvider:
    """A model running on this machine (https://ollama.com).

    Needs no key, so it is never chosen implicitly: an operator names it in
    GUIDANCE_PROVIDER, usually after a cloud provider as its fallback.
    """

    name = "ollama"

    def __init__(self) -> None:
        self._base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self._model = os.environ.get("OLLAMA_COACH_MODEL", DEFAULT_OLLAMA_COACH_MODEL)

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return True

    def check(self, timeout_seconds: float) -> None:
        resp = httpx.get(f"{self._base}/api/tags", timeout=timeout_seconds)
        if resp.status_code != 200:
            raise ProviderRefused(f"HTTP {resp.status_code}")
        names = {m.get("name") for m in resp.json().get("models", [])}
        if self._model not in names:
            raise ProviderRefused(f"model {self._model} not pulled")

    def _body(self, messages: list[dict[str, str]], temperature: float, *, stream: bool,
              as_json: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self._model, "messages": messages, "stream": stream,
                                "options": {"temperature": temperature},
                                # stay loaded between demo questions (Ollama's default is 5 min)
                                "keep_alive": OLLAMA_KEEP_ALIVE}
        if as_json:
            body["format"] = "json"
        return body

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        as_json: bool = False,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> str:
        resp = httpx.post(
            f"{self._base}/api/chat",
            json=self._body(messages, temperature, stream=False, as_json=as_json),
            timeout=max(timeout_seconds, OLLAMA_TIMEOUT_SECONDS),
        )
        if resp.status_code != 200:
            raise ProviderRefused(f"HTTP {resp.status_code}")
        return str(resp.json()["message"]["content"])

    def stream(
        self, messages: list[dict[str, str]], *, temperature: float
    ) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{self._base}/api/chat",
            json=self._body(messages, temperature, stream=True),
            timeout=OLLAMA_TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                raise ProviderRefused(f"HTTP {resp.status_code}")
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    logger.info("coach_stream_chunk_discarded provider=ollama")
                    continue
                if chunk.get("done"):
                    return
                delta = (chunk.get("message") or {}).get("content", "")
                if delta:
                    yield delta


class ChainCoachProvider:
    """Providers in order: the next one answers when one cannot.

    GUIDANCE_PROVIDER=groq,ollama keeps the demo on the cloud model and moves
    to the local one when the cloud is out of quota or unreachable. A stream
    only moves on before it has produced anything -- never mid-answer.
    """

    def __init__(self, providers: list[CoachProvider]) -> None:
        self._providers = providers
        # the provider that produced the last answer, so logs and the
        # answer's provider name tell the truth after a fallback
        self._answered: CoachProvider | None = None

    def _usable(self) -> list[CoachProvider]:
        return [p for p in self._providers if p.is_configured()]

    @property
    def _current(self) -> CoachProvider:
        return self._answered or (self._usable() or self._providers)[0]

    @property
    def name(self) -> str:
        return self._current.name

    @property
    def model(self) -> str:
        return self._current.model

    def is_configured(self) -> bool:
        return bool(self._usable())

    def check(self, timeout_seconds: float) -> None:
        last: Exception | None = None
        for provider in self._usable():
            try:
                provider.check(timeout_seconds)
                return
            except Exception as exc:  # noqa: BLE001 -- the next one may be reachable
                last = exc
        raise last or ProviderRefused("no provider configured")

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        as_json: bool = False,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> str:
        last: Exception | None = None
        for provider in self._usable():
            try:
                text = provider.complete(messages, temperature=temperature, as_json=as_json,
                                         timeout_seconds=timeout_seconds)
                self._answered = provider
                return text
            except Exception as exc:  # noqa: BLE001
                logger.warning("coach_provider_fallback from=%s reason=%s", provider.name,
                               getattr(exc, "detail", type(exc).__name__))
                last = exc
        raise last or ProviderRefused("no provider configured")

    def stream(
        self, messages: list[dict[str, str]], *, temperature: float
    ) -> Iterator[str]:
        last: Exception | None = None
        for provider in self._usable():
            produced = False
            try:
                for delta in provider.stream(messages, temperature=temperature):
                    if not produced:
                        self._answered = provider
                    produced = True
                    yield delta
                return
            except Exception as exc:  # noqa: BLE001
                if produced:
                    raise
                logger.warning("coach_stream_fallback from=%s reason=%s", provider.name,
                               getattr(exc, "detail", type(exc).__name__))
                last = exc
        raise last or ProviderRefused("no provider configured")


_BY_NAME = {"groq": GroqCoachProvider, "gemini": GeminiCoachProvider, "ollama": OllamaCoachProvider}
# a keyless local model is only used when named, never as an implicit fallthrough
_IMPLICIT = ("groq", "gemini")


def configured_coach_provider() -> CoachProvider:
    """The provider to use, preferring one that is actually usable.

    GUIDANCE_PROVIDER names one provider, or several in order separated by
    commas (a ChainCoachProvider). Naming a provider without giving it a key
    must not silently disable the coach, so an unconfigured single choice
    falls through to any cloud provider that can actually run. When none is
    configured the preferred one is still returned, so callers report
    NOT_CONFIGURED against the provider the operator meant.
    """
    named = [n.strip() for n in os.environ.get("GUIDANCE_PROVIDER", "").lower().split(",")]
    named = [n for n in named if n in _BY_NAME]
    if len(named) > 1:
        return ChainCoachProvider([_BY_NAME[n]() for n in named])
    preferred = named[0] if named else ""

    ordered: list[CoachProvider] = []
    if preferred in _BY_NAME:
        ordered.append(_BY_NAME[preferred]())
    ordered.extend(_BY_NAME[name]() for name in _IMPLICIT if name != preferred)

    for provider in ordered:
        if provider.is_configured():
            return provider
    return ordered[0]


def warm_up_local_model() -> None:
    """Load the local model into memory if GUIDANCE_PROVIDER names it, so the
    first question after a restart does not wait ~1 minute for the load.
    Best effort, meant for a background thread at startup: never raises."""
    named = [n.strip() for n in os.environ.get("GUIDANCE_PROVIDER", "").lower().split(",")]
    if "ollama" not in named:
        return
    local = OllamaCoachProvider()
    try:
        httpx.post(f"{local._base}/api/chat",
                   json={"model": local.model, "messages": [], "keep_alive": OLLAMA_KEEP_ALIVE},
                   timeout=OLLAMA_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- the coach still works, only slower
        logger.info("ollama_warm_up_skipped reason=%s", type(exc).__name__)

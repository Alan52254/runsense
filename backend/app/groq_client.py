"""Groq chat-completions call shared by the workout features.

Groq's free tier limits each model to a few thousand tokens per minute
(qwen/qwen3.8-27b: 8 000), and one workout write-up is ~2 000-3 500 of
them, so analysing a few sessions back-to-back hits HTTP 429. A 429 here
is not a failure: Groq says when the budget frees up (retry-after /
x-ratelimit-reset-tokens), and if that fits in the caller's time budget we
wait and retry the same model; otherwise the next model in the list (each
has its own quota) is tried.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import httpx

logger = logging.getLogger("app.groq_client")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqUnavailable(RuntimeError):
    pass


def api_key() -> str | None:
    key = os.environ.get("GROQ_API_KEY", "")
    return key if key.startswith("gsk_") else None


def _retry_after_s(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    reset = resp.headers.get("x-ratelimit-reset-tokens") or resp.headers.get("x-ratelimit-reset-requests")
    if reset:
        # "25.792s", "1m26.4s", "450ms"
        total = 0.0
        for amount, unit in re.findall(r"([\d.]+)(ms|m|s|h)", reset):
            total += float(amount) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
        return total or None
    return None


def chat(model: str, messages: list[dict[str, str]], *, deadline: float, max_tokens: int = 2000,
         temperature: float = 0.3, json_mode: bool = False) -> str:
    """One completion from `model`, waiting out rate limits while
    time.monotonic() < deadline. Raises GroqUnavailable otherwise."""
    key = api_key()
    if key is None:
        raise GroqUnavailable("未設定 GROQ_API_KEY")
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": min(temperature, 0.2),
                            "max_tokens": max_tokens}
    if model.startswith("openai/gpt-oss"):
        # reasoning tokens count against max_tokens: keep reasoning short
        # and leave room for the answer itself
        body.update({"reasoning_effort": "low", "include_reasoning": False, "max_tokens": max(max_tokens, 4000)})
    elif model.startswith("qwen/"):
        body["reasoning_effort"] = "none"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    while True:
        remaining = deadline - time.monotonic()
        if remaining < 3:
            raise GroqUnavailable(f"{model} 逾時")
        try:
            resp = httpx.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"}, json=body,
                              timeout=min(30.0, remaining))
        except httpx.HTTPError as exc:
            raise GroqUnavailable(f"{model} 連線失敗（{type(exc).__name__}）") from exc
        if resp.status_code == 429:
            wait = _retry_after_s(resp) or 5.0
            if time.monotonic() + wait + 5 < deadline:
                logger.info("groq_rate_limited model=%s wait=%.1fs", model, wait)
                time.sleep(wait + 0.5)
                continue
            raise GroqUnavailable(f"{model} 達到每分鐘用量上限")
        if resp.status_code != 200:
            # the body says why (e.g. json_validate_failed); server log only
            logger.warning("groq_http_error model=%s status=%s body=%s", model, resp.status_code, resp.text[:300])
            raise GroqUnavailable(f"{model} HTTP {resp.status_code}")
        content = resp.json()["choices"][0]["message"].get("content") or ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        if not content:
            raise GroqUnavailable(f"{model} 沒有回覆內容")
        return content

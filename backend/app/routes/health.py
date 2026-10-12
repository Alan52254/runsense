"""What RunSense can rely on right now, for the pre-demo check.

Required: the database (without it nothing works). Optional, each with what
happens without it: Groq (team-chat @AI stops; the rest of the coach flow
does not need it), Gemini (the health coach uses its fallback chain),
Open-Meteo (weeks are planned from the climate estimate, labelled as such).
No authentication: it reports only up / down, never a key or any data.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app import weather_forecast
from app.coach_providers import GeminiCoachProvider, GroqCoachProvider
from app.db import get_connection

router = APIRouter(tags=["health"])

_TIMEOUT_S = 3.0


def _probe(fn) -> dict[str, Any]:
    started = time.monotonic()
    try:
        detail = fn()
        return {"ok": True, "ms": round((time.monotonic() - started) * 1000), "detail": detail}
    except Exception as exc:  # any failure is "down", with the reason
        return {"ok": False, "ms": round((time.monotonic() - started) * 1000), "detail": str(exc)[:200]}


def _provider(provider) -> dict[str, Any]:
    if not provider.is_configured():
        return {"ok": False, "ms": 0, "detail": "not configured"}
    return _probe(lambda: provider.check(_TIMEOUT_S))


@router.get("/health/dependencies")
def dependencies(conn: Connection = Depends(get_connection)) -> dict[str, Any]:
    checks = {
        "database": {"required": True, **_probe(lambda: conn.execute(text("SELECT 1")).scalar_one() and None)},
        "groq": {"required": False, "without": "聊天室 @AI 暫停；整合建議課表與發布不受影響",
                 **_provider(GroqCoachProvider())},
        "gemini": {"required": False, "without": "健康教練改用備援路徑",
                   **_provider(GeminiCoachProvider())},
        "weather_forecast": {"required": False, "without": "週課表改用氣候估計（會標示）",
                             **_probe(lambda: None if weather_forecast.fetch("Taipei") else _raise("no forecast"))},
    }
    return {"ready": all(c["ok"] for c in checks.values() if c["required"]), "checks": checks}


def _raise(message: str) -> None:
    raise RuntimeError(message)

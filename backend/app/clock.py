from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime:
        ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """Deterministic adapter for tests and local demonstrations."""

    def __init__(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("fixed clock value must be timezone-aware")
        self._value = value.astimezone(timezone.utc)

    def now_utc(self) -> datetime:
        return self._value

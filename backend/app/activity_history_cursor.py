"""Private opaque cursor codec for completed-activity history."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_CURSOR_VERSION = 1
_CURSOR_KEYS = {"v", "performed_at", "id"}


class InvalidActivityHistoryCursor(ValueError):
    """Raised when a history cursor is not in the one supported canonical format."""


@dataclass(frozen=True)
class ActivityHistoryCursor:
    performed_at: datetime
    activity_id: uuid.UUID


def _canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise InvalidActivityHistoryCursor("cursor timestamp must be timezone-aware")
    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def encode_activity_history_cursor(*, performed_at: datetime, activity_id: uuid.UUID) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "performed_at": _canonical_timestamp(performed_at),
        "id": str(activity_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(cursor: str) -> dict[str, Any]:
    if not cursor or "=" in cursor:
        raise InvalidActivityHistoryCursor("cursor is not canonical base64url")
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("ascii"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidActivityHistoryCursor("cursor cannot be decoded") from exc
    if not isinstance(payload, dict) or set(payload) != _CURSOR_KEYS:
        raise InvalidActivityHistoryCursor("cursor has an unsupported shape")
    return payload


def decode_activity_history_cursor(cursor: str) -> ActivityHistoryCursor:
    payload = _decode_payload(cursor)
    if type(payload["v"]) is not int or payload["v"] != _CURSOR_VERSION:
        raise InvalidActivityHistoryCursor("cursor version is unsupported")
    if not isinstance(payload["performed_at"], str) or not isinstance(payload["id"], str):
        raise InvalidActivityHistoryCursor("cursor values have invalid types")
    try:
        performed_at = datetime.fromisoformat(payload["performed_at"].replace("Z", "+00:00"))
        activity_id = uuid.UUID(payload["id"])
    except (ValueError, TypeError) as exc:
        raise InvalidActivityHistoryCursor("cursor values are invalid") from exc
    decoded = ActivityHistoryCursor(performed_at=performed_at, activity_id=activity_id)
    canonical = encode_activity_history_cursor(
        performed_at=decoded.performed_at,
        activity_id=decoded.activity_id,
    )
    if canonical != cursor:
        raise InvalidActivityHistoryCursor("cursor is not canonical")
    return decoded

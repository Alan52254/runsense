from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.activity_history_cursor import (
    InvalidActivityHistoryCursor,
    decode_activity_history_cursor,
    encode_activity_history_cursor,
)


def _raw_cursor(payload) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_history_cursor_round_trip():
    performed_at = datetime(2026, 8, 16, 12, 34, 56, 123456, tzinfo=timezone.utc)
    activity_id = uuid.uuid4()
    encoded = encode_activity_history_cursor(
        performed_at=performed_at,
        activity_id=activity_id,
    )

    decoded = decode_activity_history_cursor(encoded)

    assert decoded.performed_at == performed_at
    assert decoded.activity_id == activity_id


@pytest.mark.parametrize(
    "cursor",
    [
        "not*base64",
        base64.urlsafe_b64encode(b"not-json").decode().rstrip("="),
        _raw_cursor([]),
        _raw_cursor({"v": 1, "performed_at": "2026-08-16T00:00:00.000000Z"}),
        _raw_cursor(
            {
                "v": 2,
                "performed_at": "2026-08-16T00:00:00.000000Z",
                "id": str(uuid.uuid4()),
            }
        ),
        _raw_cursor(
            {
                "v": 1,
                "performed_at": "not-a-date",
                "id": str(uuid.uuid4()),
            }
        ),
        _raw_cursor(
            {
                "v": 1,
                "performed_at": "2026-08-16T00:00:00.000000Z",
                "id": "not-a-uuid",
            }
        ),
        _raw_cursor(
            {
                "v": 1,
                "performed_at": "2026-08-16T00:00:00.000000Z",
                "id": str(uuid.uuid4()),
                "extra": True,
            }
        ),
    ],
)
def test_malformed_or_incompatible_history_cursor_rejected(cursor):
    with pytest.raises(InvalidActivityHistoryCursor):
        decode_activity_history_cursor(cursor)


def test_non_canonical_history_cursor_rejected():
    activity_id = uuid.uuid4()
    non_canonical = _raw_cursor(
        {
            "v": 1,
            "performed_at": "2026-08-16T00:00:00Z",
            "id": str(activity_id).upper(),
        }
    )

    with pytest.raises(InvalidActivityHistoryCursor):
        decode_activity_history_cursor(non_canonical)

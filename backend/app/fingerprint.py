"""Idempotency request-fingerprint computation.

See design.md Decision 3. This is intentionally distinct from the materialized
Training Load Trend's input_snapshot_hash: this fingerprint only exists to
detect whether a repeated (athlete_id,
client_mutation_id) create request carries the same semantic payload.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def _canonical_payload(
    duration_minutes: float,
    rpe: int,
    performed_at: datetime,
    structure: list[dict[str, object]] | None,
    distance_km: float | None,
) -> str:
    # performed_at is normalized to a single UTC representation before
    # serialization, so two requests describing the same instant but
    # differing only in timestamp formatting (trailing "Z" vs "+00:00",
    # differing sub-second precision) fingerprint identically.
    normalized_performed_at = (
        performed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    payload = {
        "duration_minutes": duration_minutes,
        "rpe": rpe,
        "performed_at": normalized_performed_at,
        # None and [] both mean "no structure supplied" -- normalized to the
        # same value so a client omitting the field on retry doesn't fingerprint
        # differently from one that explicitly sends an empty list.
        "structure": structure or [],
        "distance_km": distance_km,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_request_fingerprint(
    duration_minutes: float,
    rpe: int,
    performed_at: datetime,
    structure: list[dict[str, object]] | None = None,
    distance_km: float | None = None,
) -> str:
    canonical = _canonical_payload(duration_minutes, rpe, performed_at, structure, distance_km)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

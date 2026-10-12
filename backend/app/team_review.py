"""團隊課表審核: one row per athlete, for the coach to see across the team
which suggested weeks are waiting, stale, published or not built yet --
and why a week would change (load, a body report, the heat).

Read-only. Every figure comes from what the coach may already see: load
under `training_load`, body reports under `injury_status` (row-level
security; what is not shared is shown as not shared, never guessed), and
the coach's own draft cards. Reviewing itself happens on the athlete's
draft card in their one-to-one room.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app import chat_service

_ATHLETES = text(
    """SELECT u.id, COALESCE(u.display_name, split_part(u.email, '@', 1)) AS name
         FROM team_memberships m JOIN users u ON u.id = m.user_id
        WHERE m.team_id = :t AND m.role = 'athlete' AND m.status = 'ACTIVE' ORDER BY name""")
_CONSENTS = text(
    """SELECT scope FROM consent_grants g
        WHERE g.team_id = :t AND g.athlete_id = :a AND g.granted
          AND g.changed_at = (SELECT max(changed_at) FROM consent_grants h
                               WHERE h.team_id = g.team_id AND h.athlete_id = g.athlete_id AND h.scope = g.scope)""")
_LATEST_DRAFT = text(
    """SELECT id, status, payload, created_at FROM chat_cards
        WHERE room_id = :r AND owner_id = :o AND kind = 'plan' AND payload ? 'schedule_draft'
        ORDER BY created_at DESC LIMIT 1""")


def summary(tx: Connection, *, coach_id: uuid.UUID, team_id: uuid.UUID, today: date) -> list[dict[str, Any]]:
    rows = []
    for a in tx.execute(_ATHLETES, {"t": team_id}).all():
        scopes = set(tx.execute(_CONSENTS, {"t": team_id, "a": a.id}).scalars())
        room_id = chat_service.ensure_room(tx, team_id, a.id)
        row: dict[str, Any] = {"athlete_id": str(a.id), "name": a.name, "room_id": str(room_id),
                               "shares_load": "training_load" in scopes,
                               "shares_body": "injury_status" in scopes}

        load = tx.execute(text(
            "SELECT acute_load, chronic_load, observation_days FROM training_load_daily WHERE athlete_id = :a "
            "AND unit = 'AU' AND date <= :d ORDER BY date DESC LIMIT 1"), {"a": a.id, "d": today}).first()
        row["observation_days"] = int(load.observation_days) if load else None
        row["load_ratio"] = (round(float(load.acute_load) / float(load.chronic_load), 2)
                             if load and load.chronic_load and float(load.chronic_load) > 0 else None)

        body = tx.execute(text(
            "SELECT local_training_date, severity_band, body_part FROM injury_reports WHERE athlete_id = :a "
            "AND local_training_date >= :lo AND severity_band <> 'NONE' ORDER BY reported_at DESC LIMIT 1"),
            {"a": a.id, "lo": today - timedelta(days=7)}).first()
        row["body_report"] = ({"date": body.local_training_date.isoformat(), "severity_band": body.severity_band,
                               "body_part": body.body_part} if body else None)

        card = tx.execute(_LATEST_DRAFT, {"r": room_id, "o": coach_id}).first()
        row["draft"] = _draft_row(card) if card else None
        if card is not None:
            # what the coach decided on that draft, once confirmed or recorded
            row["draft"]["outcomes"] = dict(tx.execute(text(
                "SELECT outcome, count(*) FROM assignment_decisions WHERE card_id = :c GROUP BY outcome"),
                {"c": card.id}).all())
        row["status"] = _status(card)
        rows.append(row)
    return rows


def _draft_row(card: Any) -> dict[str, Any]:
    draft = card.payload["schedule_draft"]
    week = draft.get("week", [])
    hot = 0
    for w in (draft.get("snapshot") or {}).get("weather", {}).values():
        best = min((x["speed_loss_pct"] for x in w["windows"] if x["key"] != "midday"), default=0)
        hot += best >= 2
    return {
        "card_id": str(card.id), "version": draft.get("version"), "horizon": draft.get("horizon"),
        "review_only": bool(draft.get("review_only")),
        "changes": sum(1 for w in week if w["action"] in ("add", "adjust")),
        "adjust": sum(1 for w in week if w["action"] == "adjust"),
        "open": sum(1 for w in week if w["action"] == "open"),
        "hot_days": hot,
        "weather_source": (draft.get("inputs") or {}).get("weather"),
        "edited": any(d.get("edited") for d in card.payload["plan"]["days"]),
        "stale": draft.get("stale") or [],
        "created_at": card.created_at.isoformat(),
    }


def _status(card: Any) -> str:
    """not_built | pending | edited | stale | published | recorded | dismissed"""
    if card is None:
        return "not_built"
    draft = card.payload["schedule_draft"]
    if card.status == "confirmed":
        return "recorded" if draft.get("review_only") else "published"
    if card.status != "pending":
        return "dismissed"
    if draft.get("stale"):
        return "stale"
    return "edited" if any(d.get("edited") for d in card.payload["plan"]["days"]) else "pending"

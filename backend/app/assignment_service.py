"""Assignment Service: the only module that writes Assigned Workouts and the
coach's decision record (ADR 0004, amended).

Two kinds of caller reach it:

  a reviewed system suggestion  -- a Schedule Draft card the coach confirmed
                                   (source "review_card"), with one Decision
                                   per day saying what the coach did with it
  a coach's own workout         -- the manual assignment page ("manual_assignment")
                                   or a plan the coach wrote in chat ("chat_plan");
                                   recorded as coach_authored

Callers pass what the coach decided and nothing else. Everything a write
needs to be safe lives here: the athlete must be an active member of the
team; a day the athlete already completed is never overwritten; publishing a
day replaces that day's earlier assignments (unless the caller adds to it);
every write belongs to an assignment batch so it can be revoked; and every
decided day leaves an assignment_decisions row.

A retrospective review records decisions and writes no assignment at all.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Connection, text

from app.team_authorization import require_coach_role

SOURCES = ("review_card", "retrospective_review", "manual_assignment", "chat_plan")
OUTCOMES = ("accepted", "edited", "removed", "coach_authored", "insufficient_data")


@dataclass(frozen=True)
class DayWrite:
    """What to write for one athlete on one day: assignment records in the
    shape app/chat_service.assignment_record returns."""

    athlete_id: uuid.UUID
    athlete_name: str
    local_date: date
    records: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Decision:
    athlete_id: uuid.UUID
    local_date: date
    outcome: str
    suggested: dict[str, Any] | None = None
    final: dict[str, Any] | None = None
    changed_fields: tuple[str, ...] = ()
    reason: str | None = None


@dataclass
class Published:
    batch_id: uuid.UUID
    dates: list[str]
    athletes: list[str]
    created: int
    skipped: list[str] = field(default_factory=list)      # completed days left alone
    ineligible: list[str] = field(default_factory=list)   # not an active athlete of the team
    assignment_ids: list[uuid.UUID] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"dates": self.dates, "athletes": self.athletes, "created": self.created, "skipped": self.skipped}


def day_completed(conn: Connection, athlete_id: uuid.UUID, day: date) -> bool:
    """A day is done when its tracked assignment is marked completed, or the
    athlete has a recorded run that day."""
    if day > datetime.now(timezone.utc).date() + timedelta(days=1):
        return False
    marked = conn.execute(text("SELECT 1 FROM assigned_workouts WHERE athlete_id=:a AND local_date=:d "
                               "AND tracked AND status='COMPLETED' LIMIT 1"), {"a": athlete_id, "d": day}).first()
    ran = conn.execute(text("SELECT 1 FROM completed_activities WHERE athlete_id=:a AND local_training_date=:d "
                            "AND deleted_at IS NULL LIMIT 1"), {"a": athlete_id, "d": day}).first()
    return bool(marked or ran)


_ACTIVE_ATHLETE = text("SELECT 1 FROM team_memberships WHERE team_id=:t AND user_id=:a "
                       "AND role='athlete' AND status='ACTIVE'")
_INSERT = text(
    """INSERT INTO assigned_workouts (team_id, athlete_id, local_date, title, duration_minutes,
         intensity_label, structure, batch_id, tracked, notes)
       VALUES (:t, :a, :d, :title, :m, :l, CAST(:s AS json), :b, :tracked, :n) RETURNING id""")
_INSERT_DECISION = text(
    """INSERT INTO assignment_decisions (team_id, athlete_id, local_date, source, outcome, suggested, final,
         changed_fields, reason, card_id, draft_version, batch_id, published, decided_by)
       VALUES (:t, :a, :d, :source, :outcome, CAST(:sug AS jsonb), CAST(:fin AS jsonb), :fields, :reason,
               :card, :version, :batch, :published, :by)""")


def publish(tx: Connection, *, actor_id: uuid.UUID, team_id: uuid.UUID, source: str,
            days: list[DayWrite], card_id: uuid.UUID | None = None, draft_version: int | None = None,
            decisions: tuple[Decision, ...] = (), replace_day: bool = True) -> Published:
    """Write the coach's decision as Assigned Workouts, in one batch.

    `decisions` covers the reviewed days of a draft (including removed and
    insufficient-data days, which write nothing). Without it, every written
    day is recorded as coach_authored. Raises ValueError when nothing could
    be written."""
    if source not in SOURCES or source == "retrospective_review":
        raise ValueError(f"cannot publish from {source}")
    require_coach_role(tx, team_id, actor_id)
    batch_id = tx.execute(text(
        "INSERT INTO assignment_batches (team_id, created_by, card_id) VALUES (:t, :u, :c) RETURNING id"),
        {"t": team_id, "u": actor_id, "c": card_id}).scalar_one()
    out = Published(batch_id=batch_id, dates=[], athletes=[], created=0)
    written: set[tuple[uuid.UUID, date]] = set()
    for day in days:
        if tx.execute(_ACTIVE_ATHLETE, {"t": team_id, "a": day.athlete_id}).first() is None:
            out.ineligible.append(day.athlete_name)
            continue
        if day_completed(tx, day.athlete_id, day.local_date):
            out.skipped.append(f"{day.athlete_name} {day.local_date.month}/{day.local_date.day}")
            continue
        if replace_day:
            tx.execute(text("DELETE FROM assigned_workouts WHERE athlete_id=:a AND local_date=:d AND team_id=:t"),
                       {"a": day.athlete_id, "d": day.local_date, "t": team_id})
        for record in day.records:
            out.assignment_ids.append(tx.execute(_INSERT, {
                "t": team_id, "a": day.athlete_id, "d": day.local_date, "title": record["title"][:200],
                "m": record["duration_minutes"], "l": record["intensity_label"],
                "s": json.dumps(record.get("structure") or [], ensure_ascii=False), "b": batch_id,
                "tracked": record.get("tracked", True), "n": record.get("notes")}).scalar_one())
            out.created += 1
        written.add((day.athlete_id, day.local_date))
        if day.athlete_name not in out.athletes:
            out.athletes.append(day.athlete_name)
    if not written:
        raise ValueError("沒有可以排入的課表（選手不在隊上，或這些日子都已完成）")
    out.dates = sorted({d.isoformat() for _, d in written})

    recorded = list(decisions) or [
        Decision(athlete_id=a, local_date=d, outcome="coach_authored",
                 final={"records": [r for w in days if (w.athlete_id, w.local_date) == (a, d) for r in w.records]})
        for a, d in sorted(written)]
    _record(tx, recorded, team_id=team_id, actor_id=actor_id, source=source, card_id=card_id,
            draft_version=draft_version, batch_id=batch_id, published=True)
    tx.execute(text("UPDATE assignment_batches SET summary=CAST(:s AS jsonb) WHERE id=:id"),
               {"s": json.dumps({**out.summary(), "source": source}, ensure_ascii=False), "id": batch_id})
    return out


def record_review(tx: Connection, *, actor_id: uuid.UUID, team_id: uuid.UUID, card_id: uuid.UUID,
                  draft_version: int | None, decisions: tuple[Decision, ...]) -> int:
    """A retrospective review: the coach's decisions are recorded, nothing is
    scheduled and no history is touched."""
    require_coach_role(tx, team_id, actor_id)
    _record(tx, list(decisions), team_id=team_id, actor_id=actor_id, source="retrospective_review",
            card_id=card_id, draft_version=draft_version, batch_id=None, published=False)
    return len(decisions)


def _record(tx: Connection, decisions: list[Decision], *, team_id: uuid.UUID, actor_id: uuid.UUID, source: str,
            card_id: uuid.UUID | None, draft_version: int | None, batch_id: uuid.UUID | None,
            published: bool) -> None:
    for d in decisions:
        if d.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {d.outcome}")
        tx.execute(_INSERT_DECISION, {
            "t": team_id, "a": d.athlete_id, "d": d.local_date, "source": source, "outcome": d.outcome,
            "sug": json.dumps(d.suggested, ensure_ascii=False) if d.suggested is not None else None,
            "fin": json.dumps(d.final, ensure_ascii=False) if d.final is not None else None,
            "fields": list(d.changed_fields), "reason": (d.reason or None) and d.reason[:500],
            "card": card_id, "version": draft_version, "batch": batch_id, "published": published,
            "by": actor_id})


def revoke(tx: Connection, *, actor_id: uuid.UUID, team_id: uuid.UUID, batch_id: uuid.UUID) -> dict[str, Any]:
    """Take back a batch: its assignments go, except days already completed."""
    require_coach_role(tx, team_id, actor_id)
    rows = tx.execute(text("SELECT id, athlete_id, local_date, tracked FROM assigned_workouts WHERE batch_id=:b"),
                      {"b": batch_id}).all()
    kept, removed = 0, 0
    for r in rows:
        if r.tracked and day_completed(tx, r.athlete_id, r.local_date):
            kept += 1
            continue
        tx.execute(text("DELETE FROM assigned_workouts WHERE id=:id"), {"id": r.id})
        removed += 1
    tx.execute(text("UPDATE assignment_batches SET revoked_at=now() WHERE id=:id"), {"id": batch_id})
    return {"removed": removed, "kept": kept}


def delete(tx: Connection, *, actor_id: uuid.UUID, team_id: uuid.UUID, assignment_id: uuid.UUID) -> bool:
    require_coach_role(tx, team_id, actor_id)
    return tx.execute(text("DELETE FROM assigned_workouts WHERE id=:id AND team_id=:t RETURNING id"),
                      {"id": assignment_id, "t": team_id}).first() is not None

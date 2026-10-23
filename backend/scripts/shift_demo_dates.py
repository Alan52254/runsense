"""Shift the existing demo timeline without creating or deleting records.

Run from backend: python -m scripts.shift_demo_dates --to-date YYYY-MM-DD
Add --apply --backup PATH to apply. Anchor is the latest nondeleted completed
activity across the three exact demo personas. Repeating the same target is a
no-op. One transaction, exclusive locks, durable before-image backup and full
row comparison protect IDs, measurements and relationships. Authentication,
account/consent/audit timestamps, evidence and live weather remain untouched.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import gzip
import json
import os
from pathlib import Path
import re

from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, and_, create_engine, func, select, text

EMAILS = tuple(f"runner.{city}@runsense.demo" for city in ("taipei", "tokyo", "london"))
ATHLETE_TABLES = (
    "completed_activities", "injury_reports", "training_load_daily", "athlete_rest_days",
    "coach_proposals", "daily_guidance_cache", "activity_telemetry", "workout_analyses",
    "workout_prescriptions",
)
TEAM_TABLES = ("assigned_workouts", "assignment_batches", "assignment_decisions", "chat_rooms")
ROOM_TABLES = ("chat_messages", "chat_cards", "chat_reads")
DATE_TOKEN = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def shift_json(value, delta: timedelta):
    """Shift ISO calendar tokens (including date keys); retain numeric offsets."""
    if isinstance(value, dict):
        return {shift_json(k, delta): shift_json(v, delta) for k, v in value.items()}
    if isinstance(value, list):
        return [shift_json(v, delta) for v in value]
    if isinstance(value, str):
        def replace(match):
            try:
                return (date.fromisoformat(match[0]) + delta).isoformat()
            except ValueError:
                return match[0]
        return DATE_TOKEN.sub(replace, value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to-date", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    load_dotenv()
    if os.getenv("COMPETITION_DEMO_ONLY", "").lower() != "true":
        raise RuntimeError("COMPETITION_DEMO_ONLY=true is required")
    if args.apply and not args.backup:
        parser.error("--apply requires --backup (private gzip JSON before-images)")
    engine = create_engine(os.environ["DATABASE_URL"])
    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=engine) for name in (
        "users", "teams", "team_memberships", *ATHLETE_TABLES, *TEAM_TABLES, *ROOM_TABLES,
    )}
    with engine.begin() as conn:
        # Locks also protect the scope membership and anchor while taking backup.
        if args.apply:
            conn.execute(text("SET LOCAL lock_timeout = '10s'"))
            conn.execute(text("LOCK TABLE " + ",".join(tables) + " IN EXCLUSIVE MODE"))
        users = tables["users"]
        ids = list(conn.execute(select(users.c.id).where(users.c.email.in_(EMAILS))).scalars())
        if len(ids) != 3:
            raise RuntimeError("Expected all three exact demo personas")
        memberships = tables["team_memberships"]
        teams = list(conn.execute(select(memberships.c.team_id).where(memberships.c.user_id.in_(ids)).distinct()).scalars())
        outsiders = conn.execute(select(func.count()).select_from(memberships).where(
            memberships.c.team_id.in_(teams), ~memberships.c.user_id.in_(ids))).scalar_one()
        if outsiders:
            raise RuntimeError("Demo team contains non-demo members; refusing mixed scope")
        rooms = tables["chat_rooms"]
        room_ids = list(conn.execute(select(rooms.c.id).where(rooms.c.team_id.in_(teams))).scalars())
        activities = tables["completed_activities"]
        anchor = conn.execute(select(func.max(activities.c.local_training_date)).where(
            activities.c.athlete_id.in_(ids), activities.c.deleted_at.is_(None))).scalar_one()
        if anchor is None:
            raise RuntimeError("No demo activity anchor")
        delta = args.to_date - anchor
        report = {"anchor": str(anchor), "target": str(args.to_date), "delta_days": delta.days, "tables": {}}
        if not delta.days:
            print(json.dumps(report))
            return
        changes = []
        totals = {}
        for name in (*ATHLETE_TABLES, *TEAM_TABLES, *ROOM_TABLES):
            table = tables[name]
            scope = (table.c.athlete_id.in_(ids) if name in ATHLETE_TABLES else
                     table.c.team_id.in_(teams) if name in TEAM_TABLES else table.c.room_id.in_(room_ids))
            # Date PKs (load/cache/rest) must move furthest-first to avoid collisions.
            ordering = [c.desc() if delta.days > 0 else c.asc() for c in table.primary_key if str(c.type) == "DATE"]
            rows = conn.execute(select(table).where(scope).order_by(*ordering)).mappings().all()
            totals[name] = conn.execute(select(func.count()).select_from(table)).scalar_one()
            report["tables"][name] = len(rows)
            for row in rows:
                original = dict(row)
                updated = dict(original)
                for column in table.columns:
                    value = original[column.name]
                    if isinstance(value, date):
                        updated[column.name] = value + delta
                    elif str(column.type) in ("JSON", "JSONB"):
                        updated[column.name] = shift_json(value, delta)
                    elif name == "chat_messages" and column.name == "body":
                        updated[column.name] = shift_json(value, delta)
                changes.append((name, original, updated))
        print(json.dumps(report, indent=2))
        if not args.apply:
            return
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents accidentally overwriting the restore evidence.
        with args.backup.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb") as zipped:
                zipped.write(json.dumps({"report": report, "before_images": [
                    {"table": n, "row": old} for n, old, _ in changes
                ]}, default=str, ensure_ascii=False).encode("utf-8"))
            raw.flush()
            os.fsync(raw.fileno())
        for name, old, new in changes:
            table = tables[name]
            key = and_(*(c == old[c.name] for c in table.primary_key))
            values = {k: v for k, v in new.items() if v != old[k]}
            if values:
                if conn.execute(table.update().where(key).values(**values)).rowcount != 1:
                    raise RuntimeError(f"Unexpected update count: {name}")
        # Verify every field, not just counts: metrics and IDs must be unchanged.
        for name, old, expected in changes:
            table = tables[name]
            key = and_(*(c == expected[c.name] for c in table.primary_key))
            actual = dict(conn.execute(select(table).where(key)).mappings().one())
            if actual != expected:
                raise RuntimeError(f"Row verification failed: {name}")
        for name, count in totals.items():
            if conn.execute(select(func.count()).select_from(tables[name])).scalar_one() != count:
                raise RuntimeError(f"Record count changed: {name}")
        print("Verified every scoped row and unchanged table counts; committing transaction.")


if __name__ == "__main__":
    main()

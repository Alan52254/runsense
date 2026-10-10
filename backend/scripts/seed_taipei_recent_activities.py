"""Carry the Taipei persona's training history forward from where
seed_rich_athlete_history.py leaves it (2026-08-30) through 2026-10-15, so
the coach persona has a continuous log like the athletes do.

Follows Taipei's own elevated / tempo-heavy profile from
seed_rich_athlete_history.py (easy ~5:30/km at HR ~136-145, tempo ~4:30/km,
800 m reps ~3:50/km) on a weekly rhythm: Monday rest, Tuesday intervals,
Thursday tempo, Saturday long run, the other days easy or recovery. Every
fourth week is a lighter recovery week. Small day-to-day variation comes from
a generator seeded by the date, so re-runs produce the same rows.

Dates that already hold an activity (e.g. a manual entry) are left alone.
Idempotent (ON CONFLICT DO NOTHING, deterministic client_mutation_id), same
convention as every other script in this directory. Run manually from
backend/; application code never imports this module.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from app.training_load_store import lock_athlete_training_load, recompute_training_load
from scripts.seed_tokyo_recent_activities import _INSERT_ACTIVITY, Segment, Session

DEFAULT_EMAIL = "runner.taipei@runsense.demo"
DEFAULT_TIMEZONE = "Asia/Taipei"
DEFAULT_START = date(2026, 8, 31)
DEFAULT_END = date(2026, 10, 15)

EASY_ROUTES = ["河濱輕鬆有氧跑", "大安森林公園有氧跑", "基隆河濱慢跑", "傍晚微風有氧", "新店溪河濱慢跑"]
RECOVERY_ROUTES = ["大安河濱恢復跑", "恢復慢跑", "超慢跑輕鬆動一動", "動態恢復跑"]
TEMPO_ROUTES = ["田徑場節奏跑", "金山南路定速跑", "配速巡航跑", "大安森林公園漸進配速跑"]
LONG_ROUTES = ["基隆河濱長距離慢跑 (LSD)", "週末半馬模擬長距離", "中距離耐力維持跑"]


def _jog(kind: str, label: str, km: float, pace: float) -> Segment:
    return Segment(kind, label, km * 1000, km * pace, pace)


def _easy(rng: random.Random, *, light: bool) -> tuple[str, Session]:
    km = round(rng.uniform(6.0, 7.5) * (0.85 if light else 1), 1)
    pace = rng.uniform(322, 338)
    hr = rng.randint(135, 142)
    return rng.choice(EASY_ROUTES), Session(
        hour=rng.choice([6, 19]), rpe=4, avg_hr=hr, max_hr=hr + 12,
        training_effect="AEROBIC_BASE", aerobic_te=round(rng.uniform(2.6, 3.0), 1), anaerobic_te=0.4,
        segments=[_jog("jog", "慢跑", km, pace)],
    )


def _recovery(rng: random.Random) -> tuple[str, Session]:
    km = round(rng.uniform(4.8, 5.8), 1)
    pace = rng.uniform(345, 362)
    hr = rng.randint(122, 129)
    return rng.choice(RECOVERY_ROUTES), Session(
        hour=rng.choice([6, 20]), rpe=3, avg_hr=hr, max_hr=hr + 12,
        training_effect="RECOVERY", aerobic_te=round(rng.uniform(1.8, 2.2), 1), anaerobic_te=0.0,
        segments=[_jog("jog", "恢復跑", km, pace)],
    )


def _intervals(rng: random.Random, *, light: bool) -> tuple[str, Session]:
    reps = 4 if light else rng.choice([5, 6])
    rep_m = [800.0] * reps
    rep_paces = [round(rng.uniform(226, 236), 1) for _ in rep_m]
    rest = 120.0
    work_s = sum(m / 1000 * p for m, p in zip(rep_m, rep_paces))
    hr = rng.randint(165, 170)
    return f"間歇訓練 800m x {reps}", Session(
        hour=6, rpe=7 if light else 8, avg_hr=hr, max_hr=hr + 18,
        training_effect="VO2MAX", aerobic_te=round(rng.uniform(4.0, 4.4), 1), anaerobic_te=round(rng.uniform(2.8, 3.5), 1),
        segments=[
            _jog("warmup", "熱身", 2.0, 335),
            Segment("interval", "間歇", sum(rep_m), work_s + rest * (reps - 1), sum(rep_paces) / reps,
                    repetitions=reps, rep_distances_m=rep_m, rep_paces=rep_paces, rest_s=rest),
            _jog("cooldown", "收操", 1.5, 345),
        ],
    )


def _tempo(rng: random.Random, *, light: bool) -> tuple[str, Session]:
    km = 4.0 if light else rng.choice([5.0, 6.0])
    pace = rng.uniform(266, 276)
    hr = rng.randint(154, 159)
    return rng.choice(TEMPO_ROUTES), Session(
        hour=rng.choice([6, 19]), rpe=6 if light else 7, avg_hr=hr, max_hr=hr + 14,
        training_effect="TEMPO", aerobic_te=round(rng.uniform(3.5, 3.9), 1), anaerobic_te=round(rng.uniform(1.0, 1.6), 1),
        segments=[_jog("warmup", "熱身", 2.0, 330), _jog("tempo", "節奏", km, pace), _jog("cooldown", "收操", 1.5, 340)],
    )


def _long(rng: random.Random, *, light: bool) -> tuple[str, Session]:
    km = round(rng.uniform(9.0, 10.0) if light else rng.uniform(12.0, 14.5), 1)
    pace = rng.uniform(310, 322)
    hr = rng.randint(143, 148)
    return rng.choice(LONG_ROUTES), Session(
        hour=6, rpe=5 if light else 6, avg_hr=hr, max_hr=hr + 15,
        training_effect="AEROBIC_BASE", aerobic_te=round(rng.uniform(3.3, 3.8), 1), anaerobic_te=0.6,
        segments=[_jog("jog", "長距離", km, pace)],
    )


def build_plan(start: date, end: date) -> list[tuple[date, str, Session]]:
    plan = []
    day = start
    while day <= end:
        rng = random.Random(f"taipei-gapfill:{day.isoformat()}")
        light = ((day - start).days // 7) % 4 == 3  # every fourth week eases off
        weekday = day.weekday()  # Monday = 0
        if weekday == 0 or (light and weekday == 4):
            pass  # rest day: no row
        elif weekday == 1:
            plan.append((day, *_intervals(rng, light=light)))
        elif weekday == 3:
            plan.append((day, *_tempo(rng, light=light)))
        elif weekday == 5:
            plan.append((day, *_long(rng, light=light)))
        elif weekday in (2, 6):
            plan.append((day, *_easy(rng, light=light)))
        else:
            plan.append((day, *_recovery(rng)))
        day += timedelta(days=1)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tzinfo = ZoneInfo(args.timezone)
    rows = []
    for day_date, title, session in build_plan(args.start, args.end):
        local_dt = datetime(day_date.year, day_date.month, day_date.day, session.hour, 15, tzinfo=tzinfo)
        # an interval segment's duration already includes its rests
        duration_s = sum(s.duration_s for s in session.segments)
        distance_m = sum(s.distance_m for s in session.segments)
        duration_minutes = Decimal(str(round(duration_s / 60, 4)))
        client_mutation_id = uuid.uuid5(uuid.NAMESPACE_URL, f"taipei-gapfill:{args.email}:{day_date.isoformat()}")
        cadence = 176 + (day_date.toordinal() % 5)
        stride_m = round((distance_m / duration_s * 60) / cadence, 2)
        elevation = 8.0 + day_date.toordinal() % 30
        rows.append({
            "local_date": day_date,
            "title": title,
            "client_mutation_id": client_mutation_id,
            "request_fingerprint": f"taipei-gapfill:{client_mutation_id}",
            "provider_activity_id": f"synthetic-taipei-gapfill-{day_date:%Y%m%d}",
            "duration_minutes": duration_minutes,
            "rpe": session.rpe,
            "performed_at": local_dt.astimezone(timezone.utc),
            "timezone_snapshot": args.timezone,
            "local_training_date": day_date,
            "session_load": duration_minutes * session.rpe,
            "distance_km": round(distance_m / 1000, 2),
            "device_metrics": json.dumps({
                "avgHeartRate": session.avg_hr,
                "maxHeartRate": session.max_hr,
                "avgCadenceStepsPerMin": cadence,
                "maxCadenceStepsPerMin": cadence + 8,
                "avgStrideLengthM": stride_m,
                "elevationGainM": elevation,
                "elevationLossM": elevation,
                "calories": round(distance_m / 1000 * 64),
                "aerobicTrainingEffect": session.aerobic_te,
                "anaerobicTrainingEffect": session.anaerobic_te,
                "trainingEffectLabel": session.training_effect,
            }),
            "structure": json.dumps([s.to_json() for s in session.segments]),
        })

    print(f"Generated {len(rows)} activities for {args.email} ({args.start} .. {args.end}):")
    for row in rows:
        print(f"  {row['local_date']}  {row['distance_km']:>5}km  {float(row['duration_minutes']):5.1f}min  "
              f"RPE{row['rpe']}  {row['title']}")

    if args.dry_run:
        print("Dry run -- no database changes made.")
        return

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            athlete_id = conn.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": args.email}
            ).scalar_one_or_none()
            if athlete_id is None:
                raise RuntimeError(f"No user found for {args.email}")

            lock_athlete_training_load(conn, athlete_id)
            taken = {r[0] for r in conn.execute(
                text("SELECT local_training_date FROM completed_activities "
                     "WHERE athlete_id = :a AND deleted_at IS NULL "
                     "AND request_fingerprint NOT LIKE 'taipei-gapfill:%'"),
                {"a": athlete_id})}
            inserted = skipped = 0
            for row in rows:
                if row["local_date"] in taken:
                    skipped += 1
                    continue
                params = {k: v for k, v in row.items() if k not in ("local_date", "title")}
                inserted += conn.execute(_INSERT_ACTIVITY, {"athlete_id": athlete_id, **params}).rowcount
            print(f"Inserted {inserted} new activities ({skipped} dates already had one, "
                  f"{len(rows) - inserted - skipped} already present).")

            # recompute_training_load materializes changed_date..changed_date+27,
            # so step through the whole range
            day = args.start
            while day <= args.end:
                recompute_training_load(conn, athlete_id, day)
                day += timedelta(days=27)
            recompute_training_load(conn, athlete_id, args.end)
    finally:
        engine.dispose()

    print("Done.")


if __name__ == "__main__":
    main()

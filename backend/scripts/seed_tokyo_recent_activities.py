"""Fill the gap between Tokyo's real Garmin import (ends 2026-08-22) and
today with a few more days of fake-but-consistent activity -- specifically
so the two real coach assignments dated 2026-08-25 ("間歇", 60 min, RPE 8)
and 2026-08-27 ("速度訓練", 30 min, RPE 8-9) have a matching Completed
Activity for the coach's Athlete Detail "click a date to see what actually
happened" feature to show, instead of "no record."

Pace/HR targets match Tokyo's own real historical data (see
backfill_garmin_metrics.py output already in the DB: easy ~5:11-5:42/km,
avg HR ~150s) -- deliberately NOT the faster London profile from
seed_synthetic_garmin_history.py, since this is filling a gap in one real
athlete's own history, not fabricating a whole second athlete.

Idempotent (ON CONFLICT DO NOTHING, deterministic client_mutation_id), same
convention as every other script in this directory. Run manually from
backend/; application code never imports this module.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from app.training_load_store import lock_athlete_training_load, recompute_training_load

DEFAULT_EMAIL = "runner.tokyo@runsense.demo"
DEFAULT_TIMEZONE = "Asia/Tokyo"

_INSERT_ACTIVITY = text(
    """
    INSERT INTO completed_activities (
        athlete_id, client_mutation_id, request_fingerprint,
        provider, provider_activity_id,
        duration_minutes, rpe, performed_at,
        timezone_snapshot, local_training_date, session_load,
        distance_km, device_metrics, structure
    ) VALUES (
        :athlete_id, :client_mutation_id, :request_fingerprint,
        'garmin', :provider_activity_id,
        :duration_minutes, :rpe, :performed_at,
        :timezone_snapshot, :local_training_date, :session_load,
        :distance_km, CAST(:device_metrics AS jsonb), CAST(:structure AS json)
    )
    ON CONFLICT (athlete_id, client_mutation_id) DO NOTHING
    """
)


def _pace(sec_per_km: float) -> str:
    m, s = divmod(round(sec_per_km), 60)
    return f"{m}:{s:02d} /km"


@dataclass
class Segment:
    kind: str
    label: str
    distance_m: float
    duration_s: float
    pace_sec_per_km: float
    repetitions: int | None = None
    rep_distances_m: list[float] | None = None
    rep_paces: list[float] | None = None
    rest_s: float | None = None

    def to_json(self) -> dict:
        out = {
            "kind": self.kind,
            "label": self.label,
            "distanceMeters": round(self.distance_m),
            "durationSeconds": round(self.duration_s),
            "pace": _pace(self.pace_sec_per_km),
        }
        if self.repetitions is not None:
            out["repetitions"] = self.repetitions
            out["distancesMeters"] = [round(d) for d in self.rep_distances_m]
            out["pacesPerRep"] = [_pace(p) for p in self.rep_paces]
            out["restSeconds"] = round(self.rest_s)
        return out


@dataclass
class Session:
    hour: int
    rpe: int
    avg_hr: int
    max_hr: int
    training_effect: str
    aerobic_te: float
    anaerobic_te: float
    segments: list[Segment]


def _easy_session(hour: int, *, dist_km: float, pace: float) -> Session:
    return Session(
        hour=hour, rpe=3, avg_hr=150, max_hr=163,
        training_effect="AEROBIC_BASE", aerobic_te=2.6, anaerobic_te=0.5,
        segments=[Segment("jog", "慢跑", dist_km * 1000, dist_km * pace, pace)],
    )


def _interval_session() -> Session:
    # Matches the real "間歇" assignment: 60 min, RPE 8.
    warm_pace, cool_pace, work_pace = 330.0, 335.0, 235.0
    warm = Segment("warmup", "熱身", 2500, 2500 / 1000 * warm_pace, warm_pace)
    rep_m = [600.0] * 8
    rep_paces = [235.0, 232.0, 237.0, 233.0, 238.0, 234.0, 236.0, 231.0]
    rest_per_rep = 100.0
    work_s = sum((m / 1000) * p for m, p in zip(rep_m, rep_paces))
    interval = Segment(
        "interval", "間歇", sum(rep_m), work_s + rest_per_rep * (len(rep_m) - 1), work_pace,
        repetitions=len(rep_m), rep_distances_m=rep_m, rep_paces=rep_paces, rest_s=rest_per_rep,
    )
    cool = Segment("cooldown", "收操", 2000, 2000 / 1000 * cool_pace, cool_pace)
    return Session(
        hour=6, rpe=8, avg_hr=172, max_hr=190,
        training_effect="VO2MAX", aerobic_te=4.3, anaerobic_te=3.6,
        segments=[warm, interval, cool],
    )


def _speed_session() -> Session:
    # Matches the real "速度訓練" assignment: 30 min, RPE 8-9.
    warm_pace, cool_pace, work_pace = 320.0, 330.0, 220.0
    warm = Segment("warmup", "熱身", 2000, 2000 / 1000 * warm_pace, warm_pace)
    rep_m = [200.0] * 8
    rep_paces = [220.0, 216.0, 219.0, 217.0, 221.0, 215.0, 218.0, 214.0]
    rest_per_rep = 60.0
    work_s = sum((m / 1000) * p for m, p in zip(rep_m, rep_paces))
    interval = Segment(
        "interval", "速度", sum(rep_m), work_s + rest_per_rep * (len(rep_m) - 1), work_pace,
        repetitions=len(rep_m), rep_distances_m=rep_m, rep_paces=rep_paces, rest_s=rest_per_rep,
    )
    cool = Segment("cooldown", "收操", 1200, 1200 / 1000 * cool_pace, cool_pace)
    return Session(
        hour=6, rpe=9, avg_hr=176, max_hr=192,
        training_effect="ANAEROBIC_CAPACITY", aerobic_te=3.6, anaerobic_te=4.2,
        segments=[warm, interval, cool],
    )


def build_plan(today: date) -> list[tuple[date, Session]]:
    # 08-23 easy, 08-24 rest (no row -- a genuine rest day, not every day
    # runs), 08-25 interval (matches the real assignment), 08-26 easy,
    # 08-27 speed (matches the real assignment, today).
    return [
        (today - timedelta(days=4), _easy_session(6, dist_km=9.4, pace=328.0)),
        (today - timedelta(days=2), _interval_session()),
        (today - timedelta(days=1), _easy_session(19, dist_km=8.1, pace=333.0)),
        (today, _speed_session()),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tzinfo = ZoneInfo(args.timezone)
    today = datetime.now(tzinfo).date()
    plan = build_plan(today)

    rows = []
    for seq, (day_date, session) in enumerate(plan, start=1):
        local_dt = datetime(day_date.year, day_date.month, day_date.day, session.hour, 15, tzinfo=tzinfo)
        performed_at = local_dt.astimezone(timezone.utc)
        duration_s = sum(s.duration_s for s in session.segments)
        distance_m = sum(s.distance_m for s in session.segments)
        duration_minutes = Decimal(str(round(duration_s / 60, 4)))
        session_load = duration_minutes * session.rpe
        client_mutation_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"tokyo-gapfill:{args.email}:{day_date.isoformat()}:{seq}"
        )
        cadence = 179 + (seq % 3)
        speed_m_s = distance_m / duration_s if duration_s else 0
        stride_m = round((speed_m_s * 60) / cadence, 2) if cadence else None
        rows.append(
            {
                "local_date": day_date,
                "client_mutation_id": client_mutation_id,
                "request_fingerprint": f"tokyo-gapfill:{client_mutation_id}",
                "provider_activity_id": f"synthetic-tokyo-gapfill-{seq:03d}",
                "duration_minutes": duration_minutes,
                "rpe": session.rpe,
                "performed_at": performed_at,
                "timezone_snapshot": args.timezone,
                "local_training_date": day_date,
                "session_load": session_load,
                "distance_km": round(distance_m / 1000, 2),
                "device_metrics": json.dumps(
                    {
                        "avgHeartRate": session.avg_hr,
                        "maxHeartRate": session.max_hr,
                        "avgCadenceStepsPerMin": cadence,
                        "maxCadenceStepsPerMin": cadence + 6,
                        "avgStrideLengthM": stride_m,
                        "elevationGainM": 8.0 + seq,
                        "elevationLossM": 8.0 + seq,
                        "calories": round(distance_m / 1000 * 60),
                        "aerobicTrainingEffect": session.aerobic_te,
                        "anaerobicTrainingEffect": session.anaerobic_te,
                        "trainingEffectLabel": session.training_effect,
                    }
                ),
                "structure": json.dumps([s.to_json() for s in session.segments]),
            }
        )

    print(f"Generated {len(rows)} activities for {args.email}:")
    for row in rows:
        print(f"  {row['local_date']}  {row['distance_km']}km  {row['duration_minutes']}min  RPE{row['rpe']}")

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
            inserted = 0
            earliest = min(r["local_date"] for r in rows)
            for row in rows:
                params = {k: v for k, v in row.items() if k != "local_date"}
                result = conn.execute(_INSERT_ACTIVITY, {"athlete_id": athlete_id, **params})
                inserted += result.rowcount
            print(f"Inserted {inserted} new activities ({len(rows) - inserted} already present).")

            recompute_training_load(conn, athlete_id, earliest)
    finally:
        engine.dispose()

    print("Done.")


if __name__ == "__main__":
    main()

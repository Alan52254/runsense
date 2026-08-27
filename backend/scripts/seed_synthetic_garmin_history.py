"""Generate a fabricated multi-month Garmin-style training history for a demo
persona, and remove that persona's manually-entered activities.

Written for the London demo persona specifically: the Tokyo persona
(runner.tokyo@runsense.demo) has a real personal Garmin GDPR export imported
via import_garmin_activities.py/backfill_garmin_metrics.py/
backfill_garmin_structure.py (536 activities, 2025-01-11 to 2026-08-22).
London has no real export available, so this script fabricates a comparable
volume of history directly -- same three-script pipeline's end result
(provider='garmin', distance_km, device_metrics, structure all populated) in
one pass, generated rather than parsed from a zip.

The athlete profile is deliberately faster than Tokyo's real data at a lower
RPE for the same session type (see _build_session below) -- "a stronger
runner", not just "more of the same volume".

Idempotent by construction: client_mutation_id is uuid5-derived from a fixed
per-row key (email + local date + a same-day sequence number), so re-running
this script only ever inserts each fabricated row once (ON CONFLICT DO
NOTHING), same convention as every other script in this directory.

Run manually from backend/; application code never imports this module.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from app.training_load_store import lock_athlete_training_load, recompute_training_load

SEED = 20260827  # fixed -- reruns must regenerate the exact same history.
DEFAULT_EMAIL = "runner.london@runsense.demo"
DEFAULT_TIMEZONE = "Europe/London"
DEFAULT_SPAN_DAYS = 589  # matches Tokyo's real 2025-01-11..2026-08-22 span.

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


def _fmt_pace(sec_per_km: float) -> str:
    m, s = divmod(round(sec_per_km), 60)
    return f"{m}:{s:02d} /km"


@dataclass
class SegmentPlan:
    kind: str
    label: str
    distance_m: float
    duration_s: float
    pace_sec_per_km: float
    repetitions: int | None = None
    rep_distances_m: list[float] | None = None
    rep_paces_sec_per_km: list[float] | None = None
    rest_s: float | None = None

    def to_json(self) -> dict:
        out: dict = {
            "kind": self.kind,
            "label": self.label,
            "distanceMeters": round(self.distance_m),
            "durationSeconds": round(self.duration_s),
            "pace": _fmt_pace(self.pace_sec_per_km),
        }
        if self.repetitions is not None:
            out["repetitions"] = self.repetitions
            out["distancesMeters"] = [round(d) for d in self.rep_distances_m]
            out["pacesPerRep"] = [_fmt_pace(p) for p in self.rep_paces_sec_per_km]
            out["restSeconds"] = round(self.rest_s)
        return out


@dataclass
class SessionPlan:
    kind: str  # "recovery" | "easy" | "tempo" | "interval" | "long"
    label: str
    hour: int
    rpe: int
    avg_hr: int
    max_hr: int
    training_effect_label: str
    aerobic_te: float
    anaerobic_te: float
    segments: list[SegmentPlan] = field(default_factory=list)

    @property
    def distance_m(self) -> float:
        return sum(s.distance_m for s in self.segments)

    @property
    def duration_s(self) -> float:
        return sum(s.duration_s for s in self.segments)


# A stronger athlete than Tokyo's real data at a *lower* RPE for the same
# session type -- Tokyo's real easy runs sit around 5:11-5:42/km at RPE ~2-3
# with avg HR ~150s; this profile is roughly marathon-competitive (~sub-3:00)
# training paces.
def _build_session(rng: random.Random, kind: str, cutback: bool) -> SessionPlan:
    if kind == "recovery":
        dist = rng.uniform(4.0, 6.5) * (0.8 if cutback else 1.0)
        pace = rng.uniform(300, 325)
        rpe = rng.choice([2, 3])
        hr = (rng.randint(126, 140), rng.randint(138, 150))
        te = ("RECOVERY", rng.uniform(1.0, 1.8), rng.uniform(0.2, 0.6))
        segs = [SegmentPlan("recovery", "恢復跑", dist * 1000, dist * pace, pace)]
        hour = rng.choice([6, 7, 19, 20])
        return SessionPlan(kind, "恢復跑", hour, rpe, *hr, *te, segs)

    if kind == "easy":
        dist = rng.uniform(7.0, 12.0) * (0.75 if cutback else 1.0)
        pace = rng.uniform(265, 295)
        rpe = rng.choice([3, 4])
        hr = (rng.randint(140, 154), rng.randint(152, 165))
        te = ("AEROBIC_BASE", rng.uniform(2.0, 3.0), rng.uniform(0.3, 0.9))
        segs = [SegmentPlan("jog", "慢跑", dist * 1000, dist * pace, pace)]
        hour = rng.choice([6, 6, 7, 18, 19])
        return SessionPlan(kind, "慢跑", hour, rpe, *hr, *te, segs)

    if kind == "long":
        dist = (rng.uniform(24.0, 29.0) if rng.random() < 0.15 else rng.uniform(16.0, 23.0))
        if cutback:
            dist *= 0.7
        pace = rng.uniform(270, 296)
        rpe = rng.choice([5, 5, 6])
        hr = (rng.randint(147, 160), rng.randint(160, 172))
        te = ("AEROBIC_BASE", rng.uniform(3.5, 4.5), rng.uniform(0.8, 1.8))
        segs = [SegmentPlan("jog", "長跑", dist * 1000, dist * pace, pace)]
        hour = rng.choice([6, 6, 7])
        return SessionPlan(kind, "長跑", hour, rpe, *hr, *te, segs)

    if kind == "tempo":
        easy_pace = rng.uniform(280, 300)
        tempo_pace = rng.uniform(228, 246)
        warm_km = rng.uniform(1.5, 2.2)
        cool_km = rng.uniform(1.2, 1.8)
        tempo_km = (rng.uniform(3.5, 5.0) if cutback else rng.uniform(5.0, 8.0))
        rpe = 6 if cutback else rng.choice([6, 7])
        hr = (rng.randint(160, 172), rng.randint(174, 183))
        te = (
            rng.choice(["TEMPO", "LACTATE_THRESHOLD"]),
            rng.uniform(3.2, 4.2),
            rng.uniform(1.5, 2.5),
        )
        segs = [
            SegmentPlan("warmup", "熱身", warm_km * 1000, warm_km * easy_pace, easy_pace),
            SegmentPlan("interval", "節奏跑", tempo_km * 1000, tempo_km * tempo_pace, tempo_pace),
            SegmentPlan("cooldown", "收操", cool_km * 1000, cool_km * easy_pace, easy_pace),
        ]
        return SessionPlan(kind, "節奏跑", rng.choice([6, 6, 7]), rpe, *hr, *te, segs)

    # interval
    easy_pace = rng.uniform(280, 300)
    interval_pace = rng.uniform(200, 222)
    warm_km = rng.uniform(1.8, 2.5)
    cool_km = rng.uniform(1.2, 1.8)
    reps = rng.randint(4, 6) if cutback else rng.randint(5, 10)
    rep_m = rng.choice([400, 400, 600, 800, 1000])
    per_rep_rest_s = rng.uniform(60, 120)
    rep_distances = [rep_m * rng.uniform(0.97, 1.03) for _ in range(reps)]
    rep_paces = [interval_pace * rng.uniform(0.97, 1.03) for _ in range(reps)]
    rpe = rng.choice([7, 8]) if cutback else rng.choice([8, 9])
    hr = (rng.randint(172, 183), rng.randint(185, 195))
    te = (
        rng.choice(["VO2MAX", "ANAEROBIC_CAPACITY"]),
        rng.uniform(3.8, 4.8),
        rng.uniform(3.0, 4.2),
    )
    # Work time from each rep's own distance (meters) x pace (sec/km), plus
    # the jog-recovery time between reps -- reps-1 rest periods, not reps.
    work_s = sum((d / 1000) * p for d, p in zip(rep_distances, rep_paces))
    total_rest_s = per_rep_rest_s * (reps - 1)
    interval_seg = SegmentPlan(
        "interval",
        "間歇",
        sum(rep_distances),
        work_s + total_rest_s,
        interval_pace,
        repetitions=reps,
        rep_distances_m=rep_distances,
        rep_paces_sec_per_km=rep_paces,
        # restSeconds is the *per-rep* figure (see WorkoutAssignmentSegment's
        # doc comment in web/src/lib/types.ts) -- consumers multiply by
        # (reps-1) themselves, so storing the pre-multiplied total here would
        # double it wherever that convention is read.
        rest_s=per_rep_rest_s,
    )
    segs = [
        SegmentPlan("warmup", "熱身", warm_km * 1000, warm_km * easy_pace, easy_pace),
        interval_seg,
        SegmentPlan("cooldown", "收操", cool_km * 1000, cool_km * easy_pace, easy_pace),
    ]
    return SessionPlan(kind, "間歇", rng.choice([6, 6, 7]), rpe, *hr, *te, segs)


def _plan_day(rng: random.Random, weekday: int, cutback: bool) -> SessionPlan | None:
    """weekday: Monday=0 .. Sunday=6. Returns None for a rest day."""
    skip = rng.random() < 0.04  # travel/illness/life, independent of the plan.

    if weekday == 0:  # Monday
        if cutback or skip or rng.random() < 0.45:
            return None
        return _build_session(rng, "recovery", cutback)
    if weekday == 1:  # Tuesday
        if skip:
            return None
        return _build_session(rng, "easy", cutback)
    if weekday == 2:  # Wednesday
        if skip:
            return None
        return _build_session(rng, "easy" if cutback else "tempo", cutback)
    if weekday == 3:  # Thursday
        if cutback and rng.random() < 0.5:
            return None
        if skip:
            return None
        return _build_session(rng, "easy", cutback)
    if weekday == 4:  # Friday
        if skip:
            return None
        if cutback:
            return _build_session(rng, "easy", cutback)
        return _build_session(rng, "interval" if rng.random() < 0.7 else "easy", cutback)
    if weekday == 5:  # Saturday
        if cutback:
            return None if rng.random() < 0.5 else _build_session(rng, "easy", cutback)
        if skip or rng.random() < 0.15:
            return None
        return _build_session(rng, "easy", cutback)
    # Sunday -- long run.
    if skip:
        return None
    return _build_session(rng, "long", cutback)


def _device_metrics(rng: random.Random, session: SessionPlan) -> dict:
    dist_km = session.distance_m / 1000
    cadence = round(rng.uniform(178, 188))
    speed_m_s = session.distance_m / session.duration_s if session.duration_s else 0
    stride_m = round((speed_m_s * 60) / cadence, 2) if cadence else None
    kcal_per_km = rng.uniform(55, 65)
    return {
        "avgHeartRate": session.avg_hr,
        "maxHeartRate": session.max_hr,
        "avgCadenceStepsPerMin": cadence,
        "maxCadenceStepsPerMin": cadence + round(dist_km % 6) + 4,
        "avgStrideLengthM": stride_m,
        "elevationGainM": round(5 + (dist_km * 3.1) % 32, 1),
        "elevationLossM": round(5 + (dist_km * 2.3) % 30, 1),
        "calories": round(dist_km * kcal_per_km),
        "aerobicTrainingEffect": round(session.aerobic_te, 1),
        "anaerobicTrainingEffect": round(session.anaerobic_te, 1),
        "trainingEffectLabel": session.training_effect_label,
    }


def generate_rows(email: str, tz_name: str, span_days: int, end_date: date) -> list[dict]:
    rng = random.Random(SEED)
    tzinfo = ZoneInfo(tz_name)
    start_date = end_date - timedelta(days=span_days)

    rows: list[dict] = []
    seq = 0
    day = start_date
    while day <= end_date:
        week_index = (day - start_date).days // 7
        cutback = week_index % 4 == 3
        session = _plan_day(rng, day.weekday(), cutback)
        if session is not None and session.duration_s > 0:
            local_dt = datetime(day.year, day.month, day.day, session.hour, rng.randint(0, 55), tzinfo=tzinfo)
            performed_at = local_dt.astimezone(timezone.utc)
            duration_minutes = Decimal(str(round(session.duration_s / 60, 4)))
            rpe = session.rpe
            session_load = duration_minutes * rpe
            seq += 1
            client_mutation_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"synthetic-garmin:{email}:{day.isoformat()}:{seq}"
            )
            rows.append(
                {
                    "client_mutation_id": client_mutation_id,
                    "request_fingerprint": f"synthetic-garmin:{client_mutation_id}",
                    "provider_activity_id": f"synthetic-{email.split('@')[0]}-{seq:06d}",
                    "duration_minutes": duration_minutes,
                    "rpe": rpe,
                    "performed_at": performed_at,
                    "timezone_snapshot": tz_name,
                    "local_training_date": day,
                    "session_load": session_load,
                    "distance_km": round(session.distance_m / 1000, 2),
                    "device_metrics": _device_metrics(rng, session),
                    "structure": [s.to_json() for s in session.segments],
                }
            )
        day += timedelta(days=1)

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--span-days", type=int, default=DEFAULT_SPAN_DAYS)
    parser.add_argument(
        "--keep-manual",
        action="store_true",
        help="Skip deleting the athlete's existing provider='manual' activities.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Generate and report counts without writing to the DB"
    )
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()

    rows = generate_rows(args.email, args.timezone, args.span_days, today)
    for row in rows:
        row["device_metrics"] = json.dumps(row["device_metrics"])
        row["structure"] = json.dumps(row["structure"])

    print(f"Generated {len(rows)} synthetic garmin activities for {args.email}.")
    if rows:
        print(f"Date range: {rows[0]['local_training_date']} to {rows[-1]['local_training_date']}")

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
                raise RuntimeError(f"No user found for {args.email} -- run seed_demo_personas.py first")

            lock_athlete_training_load(conn, athlete_id)

            if not args.keep_manual:
                deleted = conn.execute(
                    text(
                        "DELETE FROM completed_activities "
                        "WHERE athlete_id = :athlete_id AND provider = 'manual'"
                    ),
                    {"athlete_id": athlete_id},
                ).rowcount
                print(f"Deleted {deleted} manual activities for {args.email}.")

            inserted = 0
            for row in rows:
                result = conn.execute(_INSERT_ACTIVITY, {"athlete_id": athlete_id, **row})
                inserted += result.rowcount
            print(f"Inserted {inserted} new synthetic garmin activities ({len(rows) - inserted} already present, unchanged).")

            recompute_training_load(conn, athlete_id, today - timedelta(days=27))
    finally:
        engine.dispose()

    print("Done.")


if __name__ == "__main__":
    main()

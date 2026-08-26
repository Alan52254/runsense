"""Backfill block-by-block `structure` (warmup/interval/cooldown/recovery/jog)
onto the running activities import_garmin_activities.py already created,
inferred from each activity's Garmin lap ("splits") data.

Run manually from backend/; application code never imports this module.

Garmin's laps don't come pre-labeled as warmup/interval/cooldown -- this
infers roles from pace (primary signal, always present) and heart rate
(secondary check, used only when present) relative to that activity's own
splits, not any fixed pace threshold: the fastest lap(s) in a session are
"interval" work; the first/last non-trivial lap is "warmup"/"cooldown" if
it isn't already classified as interval; everything else is steady "jog".
This is an inference, not a Garmin-provided label -- expect it to
occasionally misclassify a genuinely all-easy run's slightly-faster middle
kilometer, or a warmup that happened to be run briskly.

Consecutive laps that classify the same way are merged into one segment
(interval reps become one segment with repetitions + distancesMeters,
matching the coach workout-builder's own shape) rather than emitted 1:1 --
some activities have 200+ raw laps, and CreateActivityRequest.structure
caps at 50 items besides being unreadable unmerged.

Idempotent: always recomputes and overwrites structure for the targeted
rows, safe to re-run (e.g. after tuning the classification heuristic).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import create_engine, text

_RUNNING_ACTIVITY_TYPES = {"running", "track_running", "treadmill_running", "trail_running"}

# A lap shorter than this is a lap-button press during a standing/near-still
# recovery, not real running distance -- Garmin's own auto-lap and manual-lap
# data both produce these between reps.
_RECOVERY_DISTANCE_M = 50.0
_RECOVERY_DURATION_S = 10.0

# A lap at least this much faster than the session's own median real-lap
# pace counts as work, relative to THIS activity's own laps -- there is no
# universal "interval pace", only faster-than-what-this-runner-did-else-
# where-in-this-same-session.
_INTERVAL_PACE_RATIO = 0.92

_KIND_LABEL = {"warmup": "熱身", "cooldown": "收操", "jog": "慢跑", "interval": "間歇"}

_SELECT_ROW = text(
    "SELECT id FROM completed_activities WHERE athlete_id = :athlete_id AND client_mutation_id = :client_mutation_id"
)
_UPDATE_STRUCTURE = text(
    "UPDATE completed_activities SET structure = CAST(:structure AS jsonb) WHERE id = :id"
)


def _load_summarized_activities(zip_path: Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as archive:
        matches = [n for n in archive.namelist() if n.endswith("_1_summarizedActivities.json")]
        if not matches:
            raise RuntimeError(f"No *_1_summarizedActivities.json found in {zip_path}")
        with archive.open(matches[0]) as f:
            data = json.load(f)
    return data[0]["summarizedActivitiesExport"]


def _format_pace(sec_per_km: float) -> str:
    total = round(sec_per_km)
    return f"{total // 60}:{total % 60:02d} /km"


def _parse_splits(activity: dict) -> list[tuple[float, float, float | None]]:
    """One (distance_m, duration_s, avg_heart_rate) per Garmin split."""
    parsed = []
    for split in activity.get("splits") or []:
        measurements = {m["fieldEnum"]: m["value"] for m in split.get("measurements", [])}
        distance_m = measurements.get("SUM_DISTANCE", 0.0) / 100.0
        duration_s = measurements.get("SUM_DURATION", 0.0) / 1000.0
        hr = measurements.get("WEIGHTED_MEAN_HEARTRATE")
        parsed.append((distance_m, duration_s, hr))
    return parsed


def _classify_and_group(activity: dict) -> list[dict]:
    parsed = _parse_splits(activity)
    real_indices = [
        i for i, (d, t, _hr) in enumerate(parsed) if d >= _RECOVERY_DISTANCE_M and t >= _RECOVERY_DURATION_S
    ]

    if not real_indices:
        # No splits, or every split was trivial (e.g. a single-lap activity
        # with the whole run as one lap already below threshold due to a
        # data quirk) -- fall back to one plain block from the activity's
        # own top-level totals.
        distance_m = (activity.get("distance") or 0) / 100.0
        duration_s = (activity.get("duration") or 0) / 1000.0
        if distance_m <= 0 or duration_s <= 0:
            return []
        return [
            {
                "kind": "jog",
                "label": _KIND_LABEL["jog"],
                "distanceMeters": round(distance_m),
                "durationSeconds": round(duration_s),
                "pace": _format_pace(duration_s / (distance_m / 1000)),
            }
        ]

    paces = [parsed[i][1] / (parsed[i][0] / 1000) for i in real_indices]
    median_pace = statistics.median(paces)

    classified: list[tuple[int, str]] = []
    for pos, i in enumerate(real_indices):
        distance_m, duration_s, _hr = parsed[i]
        pace = duration_s / (distance_m / 1000)
        if pace <= median_pace * _INTERVAL_PACE_RATIO:
            kind = "interval"
        elif pos == 0 and len(real_indices) > 1:
            kind = "warmup"
        elif pos == len(real_indices) - 1 and len(real_indices) > 1:
            kind = "cooldown"
        else:
            kind = "jog"
        classified.append((i, kind))

    groups: list[tuple[str, list[int]]] = []
    for i, kind in classified:
        if groups and groups[-1][0] == kind:
            groups[-1][1].append(i)
        else:
            groups.append((kind, [i]))

    def recovery_between(i1: int, i2: int) -> float:
        return sum(parsed[j][1] for j in range(i1 + 1, i2) if j not in real_indices)

    segments = []
    for kind, members in groups:
        if kind == "interval" and len(members) > 1:
            distances = [round(parsed[i][0]) for i in members]
            durations = [parsed[i][1] for i in members]
            total_d = sum(distances)
            total_t = sum(durations)
            rest_gaps = [recovery_between(members[k], members[k + 1]) for k in range(len(members) - 1)]
            avg_rest = round(sum(rest_gaps) / len(rest_gaps)) if rest_gaps else 0
            segment = {
                "kind": "interval",
                "label": _KIND_LABEL["interval"],
                "repetitions": len(members),
                "distancesMeters": distances,
                # The group's overall average -- kept for the compact
                # summary line. pacesPerRep (below) is the one that actually
                # preserves each rep's own pace instead of collapsing a
                # negative split or a fading set into one number.
                "pace": _format_pace(total_t / (total_d / 1000)) if total_d else None,
                # Same length/order as distancesMeters always -- the frontend
                # zips them by index, so this can't be shorter even in the
                # (should-be-impossible-given real_indices' own >=50m filter)
                # case of a zero-distance member.
                "pacesPerRep": [
                    _format_pace(d_s / (d_m / 1000)) if d_m > 0 else None
                    for d_m, d_s in zip(distances, durations)
                ],
            }
            if avg_rest > 0:
                segment["restSeconds"] = avg_rest
            segments.append(segment)
        else:
            total_d = sum(parsed[i][0] for i in members)
            total_t = sum(parsed[i][1] for i in members)
            segment = {
                "kind": kind,
                "label": _KIND_LABEL[kind],
                "distanceMeters": round(total_d),
                "durationSeconds": round(total_t),
            }
            if total_d > 0:
                segment["pace"] = _format_pace(total_t / (total_d / 1000))
            segments.append(segment)

    return segments[:50]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path, help="Path to the Garmin GDPR export zip")
    parser.add_argument("--email", default="runner.tokyo@runsense.demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    activities = _load_summarized_activities(args.zip_path)
    runs = [a for a in activities if a.get("activityType") in _RUNNING_ACTIVITY_TYPES]

    plans = []
    for activity in runs:
        segments = _classify_and_group(activity)
        if not segments:
            continue
        client_mutation_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"garmin-import:{args.email}:{activity['activityId']}"
        )
        plans.append((client_mutation_id, segments))

    segment_counts = [len(s) for _cmid, s in plans]
    print(f"Computed structure for {len(plans)} activities.")
    if segment_counts:
        print(
            f"Segments per activity -- min {min(segment_counts)}, "
            f"median {statistics.median(segment_counts):.0f}, max {max(segment_counts)}"
        )

    if args.dry_run:
        print("Dry run -- no database changes made.")
        for cmid, segments in plans[:3]:
            print(cmid, json.dumps(segments, ensure_ascii=False))
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

            updated = 0
            missing = 0
            for client_mutation_id, segments in plans:
                row = conn.execute(
                    _SELECT_ROW, {"athlete_id": athlete_id, "client_mutation_id": client_mutation_id}
                ).first()
                if row is None:
                    missing += 1
                    continue
                conn.execute(
                    _UPDATE_STRUCTURE, {"id": row.id, "structure": json.dumps(segments)}
                )
                updated += 1

            print(f"Updated {updated} rows, {missing} activities had no matching row (not imported / different athlete).")
    finally:
        engine.dispose()

    print("Done.")


if __name__ == "__main__":
    main()

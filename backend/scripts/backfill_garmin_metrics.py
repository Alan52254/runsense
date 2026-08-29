"""Backfill distance_km, device_metrics (heart rate, cadence, elevation,
calories, training effect), and the correct provider/provider_activity_id
onto the running activities import_garmin_activities.py already created.

import_garmin_activities.py's INSERT never set provider (it has a column
default of 'manual', shared with genuinely-manual log entries), so every
row it created reads as "手動輸入"/Manual in the UI regardless of source.
This corrects that to 'garmin' + the real Garmin activityId as
provider_activity_id, which is exactly what
uq_completed_activities_provider_activity (see migration 0001) exists to
support.

Run manually from backend/; application code never imports this module.

Unit conventions below were verified, not assumed, by cross-referencing
real activity names against known geography: several "中正區"/"永和區"
(central Taipei, near sea level) activities showed elevationGain/
minElevation/maxElevation in the high hundreds to low thousands -- only
consistent with the export's internal centimeter convention (matching
distance/duration), not meters, which would imply 1000-3000m mountains in
flat downtown Taipei. Similarly, avgRunCadence (~85-95 in this export) is
half of avgDoubleCadence (~170-190) for the same activity, and only
avgDoubleCadence reconciles with avgStrideLength via
speed = cadence(steps/min) x stride_length(m) / 60 -- avgRunCadence is a
single-foot count, avgDoubleCadence is the real steps/min figure, so that's
what's stored here as "cadence".

`calories` is mislabeled too: its value is byte-for-byte identical to the
sum of that activity's own per-lap SUM_ENERGY measurements, which the
export's own unitEnum labels KILOJOULE -- e.g. a 37.9-minute run reporting
"calories": 1428.8 would be ~9x too high at face value (roughly 38
kcal/min, versus a physiologically-plausible ~9 kcal/min at that HR/pace).
Converted to real kcal here via the standard kJ-to-kcal factor (/4.184).

Idempotent: always recomputes and overwrites distance_km/device_metrics for
the targeted rows, safe to re-run.
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

_SELECT_ROW = text(
    "SELECT id FROM completed_activities WHERE athlete_id = :athlete_id AND client_mutation_id = :client_mutation_id"
)
_UPDATE_ROW = text(
    "UPDATE completed_activities SET distance_km = :distance_km, "
    "device_metrics = CAST(:device_metrics AS jsonb), "
    "provider = 'garmin', provider_activity_id = :provider_activity_id WHERE id = :id"
)


def _load_summarized_activities(zip_path: Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as archive:
        matches = [n for n in archive.namelist() if n.endswith("_1_summarizedActivities.json")]
        if not matches:
            raise RuntimeError(f"No *_1_summarizedActivities.json found in {zip_path}")
        with archive.open(matches[0]) as f:
            data = json.load(f)
    return data[0]["summarizedActivitiesExport"]


def _round1(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _extract(activity: dict) -> tuple[float | None, dict[str, object]]:
    distance_km = None
    if activity.get("distance"):
        distance_km = round(activity["distance"] / 100_000, 2)

    metrics: dict[str, object] = {}
    if activity.get("avgHr") is not None:
        metrics["avgHeartRate"] = round(activity["avgHr"])
    if activity.get("maxHr") is not None:
        metrics["maxHeartRate"] = round(activity["maxHr"])
    if activity.get("avgDoubleCadence") is not None:
        metrics["avgCadenceStepsPerMin"] = round(activity["avgDoubleCadence"])
    if activity.get("maxDoubleCadence") is not None:
        metrics["maxCadenceStepsPerMin"] = round(activity["maxDoubleCadence"])
    if activity.get("avgStrideLength") is not None:
        metrics["avgStrideLengthM"] = _round1(activity["avgStrideLength"] / 100)
    if activity.get("elevationGain") is not None:
        metrics["elevationGainM"] = _round1(activity["elevationGain"] / 100)
    if activity.get("elevationLoss") is not None:
        metrics["elevationLossM"] = _round1(activity["elevationLoss"] / 100)
    if activity.get("calories") is not None:
        metrics["calories"] = round(activity["calories"] / 4.184)  # kJ -> kcal, see module docstring
    if activity.get("aerobicTrainingEffect") is not None:
        metrics["aerobicTrainingEffect"] = _round1(activity["aerobicTrainingEffect"])
    if activity.get("anaerobicTrainingEffect") is not None:
        metrics["anaerobicTrainingEffect"] = _round1(activity["anaerobicTrainingEffect"])
    if activity.get("trainingEffectLabel"):
        metrics["trainingEffectLabel"] = activity["trainingEffectLabel"]

    return distance_km, metrics


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
        distance_km, metrics = _extract(activity)
        client_mutation_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"garmin-import:{args.email}:{activity['activityId']}"
        )
        plans.append((client_mutation_id, distance_km, metrics, str(activity["activityId"])))

    metric_counts = [len(m) for _cmid, _d, m, _pid in plans]
    print(f"Computed metrics for {len(plans)} activities.")
    if metric_counts:
        print(
            f"Fields per activity -- min {min(metric_counts)}, "
            f"median {statistics.median(metric_counts):.0f}, max {max(metric_counts)}"
        )

    if args.dry_run:
        print("Dry run -- no database changes made.")
        for cmid, distance_km, metrics, provider_activity_id in plans[:3]:
            print(cmid, distance_km, provider_activity_id, json.dumps(metrics, ensure_ascii=False))
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
            for client_mutation_id, distance_km, metrics, provider_activity_id in plans:
                row = conn.execute(
                    _SELECT_ROW, {"athlete_id": athlete_id, "client_mutation_id": client_mutation_id}
                ).first()
                if row is None:
                    missing += 1
                    continue
                conn.execute(
                    _UPDATE_ROW,
                    {
                        "id": row.id,
                        "distance_km": distance_km,
                        "device_metrics": json.dumps(metrics),
                        "provider_activity_id": provider_activity_id,
                    },
                )
                updated += 1

            print(f"Updated {updated} rows, {missing} activities had no matching row.")
    finally:
        engine.dispose()

    print("Done.")


if __name__ == "__main__":
    main()

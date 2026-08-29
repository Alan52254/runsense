"""Seed realistic 28-day Garmin activities and training load for all three
demo personas, each with its own distinct training-load profile.

Two bugs fixed here (found while investigating wrong AU numbers and a
recorded-vs-displayed heart rate mismatch in the demo):

1. This script used to insert the *same* hardcoded 27-day schedule onto
   every user in the DB, on top of seed_demo_personas.py's own baseline
   activities (`request_fingerprint LIKE 'demo-seed:%'`) -- which cover
   several of the same calendar dates (offsets 1/3/5/14 collide). Two
   Completed Activities landing on one Local Training Date double-counts
   that day's session_load into acute/chronic training load, and gave all
   three athletes numerically identical recent-28-day AU. Fixed by
   deleting each athlete's demo-seed rows inside the schedule's date range
   before inserting, and by giving each athlete a distinct schedule
   (Taipei: elevated/tempo-heavy; Tokyo: steady aerobic; London:
   reduced/recovery) instead of copy-pasting one list three times.

2. device_metrics keys were snake_case (avg_heart_rate, max_heart_rate,
   ...). Every other producer -- the real Garmin import
   (import_garmin_activities.py/backfill_garmin_metrics.py), the
   synthetic Garmin generators, and web/src/lib/types.ts's
   ActivityDeviceMetrics -- uses camelCase (avgHeartRate, maxHeartRate,
   ...), and backend/app/routes/activities.py returns device_metrics
   verbatim with no key normalization. So every row this script wrote was
   invisible to the frontend's real-data reads (peak HR tile, activity
   detail "Heart rate" stat), which silently fell back to a synthetic
   RPE-based estimate or a hardcoded placeholder instead of the real
   recorded number. Fixed by switching to camelCase.
"""

from __future__ import annotations

import os
import sys
import uuid
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

# Force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text
from app.training_load_store import lock_athlete_training_load, recompute_training_load

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/runsense")

# app/training_load.py's own data_quality rule (not a "demo mode" threshold --
# it applies identically to every athlete, real or seeded) needs at least 21
# distinct observation days inside the trailing 28-day window before it will
# report anything but data_quality=INSUFFICIENT / load_ratio=None. A schedule
# with fewer than 21 distinct days can *never* clear that bar no matter how
# much real time passes, since observation_days is capped at however many
# calendar dates the schedule actually covers. Taipei and Tokyo (below) are
# built dense enough (22-23 distinct days out of 27) to clear it with a
# little margin; London is deliberately left sparse (see its own comment) so
# its INSUFFICIENT/LOW data_quality is a true, demonstrable state rather than
# an accident of scheduling.
#
# (day_offset, duration_min, rpe, distance_km, avg_hr, max_hr, avg_cad, max_cad, elev_gain, calories, te, te_label, title)
_TAIPEI_SCHEDULE = [
    (1, 45, 6, 8.2, 154, 168, 178, 186, 35, 510, 3.6, "TEMPO", "大安森林公園漸進配速跑"),
    (2, 35, 4, 6.0, 136, 148, 174, 180, 15, 380, 2.7, "AEROBIC_BASE", "河濱輕鬆有氧跑"),
    (3, 50, 7, 10.0, 165, 182, 176, 184, 160, 640, 4.1, "THRESHOLD", "劍南路丘陵肌耐力跑"),
    (4, 30, 3, 5.0, 128, 140, 172, 178, 10, 300, 2.0, "RECOVERY", "大安河濱恢復跑"),
    (5, 40, 5, 7.5, 158, 172, 180, 188, 12, 470, 3.8, "TEMPO", "田徑場節奏跑 (Tempo Run)"),
    (6, 60, 6, 12.0, 144, 158, 176, 182, 45, 750, 3.5, "AEROBIC_BASE", "基隆河濱長距離慢跑 (LSD)"),
    (7, 30, 3, 5.2, 126, 138, 172, 178, 8, 290, 2.0, "RECOVERY", "恢復慢跑 (Active Recovery)"),
    (8, 35, 4, 6.2, 138, 150, 175, 181, 15, 380, 2.7, "AEROBIC_BASE", "河濱有氧跑"),
    (9, 45, 7, 8.5, 168, 186, 184, 194, 20, 580, 4.3, "VO2MAX", "間歇訓練 800m x 5"),
    (10, 35, 4, 6.0, 134, 145, 174, 180, 14, 370, 2.6, "AEROBIC_BASE", "輕鬆排乳酸跑"),
    (11, 35, 4, 6.0, 136, 148, 174, 180, 14, 370, 2.6, "AEROBIC_BASE", "輕鬆跑"),
    (12, 55, 6, 11.0, 152, 166, 178, 184, 40, 680, 3.7, "TEMPO", "配速巡航跑"),
    (13, 30, 3, 5.0, 126, 138, 172, 178, 8, 290, 2.0, "RECOVERY", "恢復跑"),
    (14, 40, 5, 7.0, 140, 152, 176, 182, 22, 440, 3.1, "AEROBIC_BASE", "有氧基礎跑"),
    (15, 65, 6, 13.5, 146, 162, 176, 182, 55, 840, 3.8, "AEROBIC_BASE", "週末半馬模擬長距離"),
    (16, 35, 4, 6.0, 135, 147, 174, 180, 14, 365, 2.6, "AEROBIC_BASE", "輕鬆跑"),
    (17, 35, 3, 5.8, 128, 140, 172, 178, 10, 330, 2.2, "RECOVERY", "動態恢復跑"),
    (18, 40, 4, 6.8, 139, 151, 175, 181, 16, 400, 2.8, "AEROBIC_BASE", "河濱慢跑"),
    (19, 50, 6, 9.5, 150, 165, 178, 184, 30, 600, 3.6, "TEMPO", "金山南路定速跑"),
    (21, 40, 4, 7.2, 138, 150, 174, 180, 18, 430, 2.9, "AEROBIC_BASE", "傍晚微風有氧"),
    (23, 45, 7, 8.0, 167, 185, 182, 192, 15, 560, 4.2, "VO2MAX", "亞索 800 間歇"),
    (25, 30, 3, 5.0, 122, 134, 170, 176, 6, 260, 1.8, "RECOVERY", "超慢跑輕鬆動一動"),
    (27, 55, 5, 10.5, 142, 156, 176, 182, 35, 660, 3.4, "AEROBIC_BASE", "中距離耐力維持跑"),
]
# 23 distinct days out of 27 -- rest on 20/22/24/26, comfortably above the 21-day bar.

# Steady aerobic base-building -- moderate, consistent volume, no hard days.
_TOKYO_SCHEDULE = [
    (1, 40, 4, 7.0, 142, 156, 175, 181, 15, 420, 2.8, "AEROBIC_BASE", "皇居ランニングコース イージーラン"),
    (2, 35, 3, 5.5, 137, 149, 174, 179, 9, 335, 2.3, "RECOVERY", "リカバリージョグ"),
    (3, 45, 4, 7.8, 145, 158, 176, 182, 18, 460, 2.9, "AEROBIC_BASE", "多摩川サイクリングロード ジョグ"),
    (4, 45, 4, 7.6, 144, 157, 176, 181, 17, 450, 2.8, "AEROBIC_BASE", "隅田川イージーラン"),
    (5, 50, 5, 8.8, 150, 163, 177, 183, 20, 520, 3.1, "AEROBIC_BASE", "代々木公園 中距離走"),
    (6, 40, 4, 6.9, 142, 155, 175, 180, 15, 415, 2.7, "AEROBIC_BASE", "夜間軽め走"),
    (7, 35, 3, 5.8, 138, 150, 174, 179, 10, 350, 2.4, "RECOVERY", "リカバリージョグ"),
    (8, 45, 4, 7.4, 143, 156, 175, 181, 16, 445, 2.8, "AEROBIC_BASE", "多摩川イージーラン"),
    (9, 45, 4, 7.5, 143, 157, 175, 181, 16, 440, 2.8, "AEROBIC_BASE", "隅田川テラス イージーラン"),
    (10, 35, 3, 5.6, 138, 150, 174, 179, 10, 340, 2.3, "RECOVERY", "リカバリージョグ"),
    (11, 50, 5, 9.0, 149, 162, 177, 183, 22, 530, 3.2, "AEROBIC_BASE", "皇居 定常走"),
    (12, 45, 4, 7.5, 144, 157, 176, 181, 17, 450, 2.8, "AEROBIC_BASE", "皇居イージーラン"),
    (13, 40, 4, 6.8, 141, 155, 175, 180, 14, 410, 2.7, "AEROBIC_BASE", "夜間軽め走"),
    (14, 40, 4, 6.8, 141, 154, 175, 180, 14, 410, 2.7, "AEROBIC_BASE", "代々木公園ジョグ"),
    (15, 60, 5, 11.0, 148, 161, 176, 182, 30, 640, 3.3, "AEROBIC_BASE", "週末ロング走"),
    (16, 35, 3, 5.5, 137, 149, 173, 179, 9, 335, 2.3, "RECOVERY", "リカバリージョグ"),
    (17, 35, 3, 5.5, 137, 149, 173, 179, 9, 340, 2.3, "RECOVERY", "リカバリージョグ"),
    (19, 45, 4, 7.6, 144, 157, 176, 181, 17, 450, 2.8, "AEROBIC_BASE", "多摩川イージーラン"),
    (21, 50, 5, 8.9, 149, 162, 177, 182, 21, 525, 3.1, "AEROBIC_BASE", "代々木公園 定常走"),
    (23, 40, 4, 6.9, 142, 155, 175, 180, 15, 415, 2.7, "AEROBIC_BASE", "隅田川イージーラン"),
    (25, 35, 3, 5.6, 138, 150, 174, 179, 10, 345, 2.3, "RECOVERY", "リカバリージョグ"),
    (27, 55, 5, 10.0, 147, 160, 176, 182, 26, 590, 3.2, "AEROBIC_BASE", "皇居 週末ロング走"),
]
# 22 distinct days out of 27 -- rest on 18/20/22/24/26, comfortably above the 21-day bar.

# Reduced/recovery block -- lower volume and intensity than the other two,
# with more rest between sessions (a taper or return-from-niggle pattern).
_LONDON_SCHEDULE = [
    (2, 30, 3, 5.0, 130, 142, 172, 178, 20, 300, 2.1, "RECOVERY", "Regent's Park easy jog"),
    (5, 35, 3, 5.8, 133, 145, 173, 179, 25, 340, 2.3, "RECOVERY", "Thames Path recovery run"),
    (8, 40, 4, 6.5, 138, 150, 174, 180, 30, 390, 2.6, "AEROBIC_BASE", "Hyde Park easy run"),
    (11, 30, 3, 4.8, 129, 141, 171, 177, 15, 290, 2.0, "RECOVERY", "Easy shakeout jog"),
    (14, 45, 4, 7.2, 140, 153, 175, 181, 35, 430, 2.7, "AEROBIC_BASE", "Richmond Park steady run"),
    (18, 35, 3, 5.5, 132, 144, 172, 178, 22, 330, 2.2, "RECOVERY", "Recovery jog"),
    (21, 40, 4, 6.8, 137, 150, 174, 180, 28, 400, 2.6, "AEROBIC_BASE", "Canal towpath easy run"),
    (25, 30, 3, 5.0, 130, 142, 172, 178, 18, 300, 2.1, "RECOVERY", "Easy jog"),
]

_ATHLETE_SCHEDULES: dict[str, list[tuple]] = {
    "runner.taipei@runsense.demo": _TAIPEI_SCHEDULE,
    "runner.tokyo@runsense.demo": _TOKYO_SCHEDULE,
    "runner.london@runsense.demo": _LONDON_SCHEDULE,
}

_TIMEZONE_BY_EMAIL = {
    "runner.taipei@runsense.demo": ("Asia/Taipei", 8),
    "runner.tokyo@runsense.demo": ("Asia/Tokyo", 9),
    "runner.london@runsense.demo": ("Europe/London", 1),  # BST offset in August
}

_DELETE_BASELINE_IN_RANGE = text(
    """
    DELETE FROM completed_activities
     WHERE athlete_id = :athlete_id
       AND request_fingerprint LIKE 'demo-seed:%'
       AND local_training_date BETWEEN :start_date AND :end_date
    """
)

# Wipe this athlete's *entire* prior rich-seed set first, not just the dates
# the current schedule happens to reuse -- otherwise changing offsets between
# runs (as happens when giving each athlete a distinct profile) leaves old
# rows behind with mutation ids the new schedule never revisits, so ON
# CONFLICT DO UPDATE can't reach and clean them up.
_DELETE_ALL_RICH_SEED = text(
    "DELETE FROM completed_activities WHERE athlete_id = :athlete_id "
    "AND request_fingerprint LIKE 'rich-seed:%'"
)


def seed_rich_history():
    print("=" * 60)
    print("Seeding 28-Day Rich Training History (per-athlete distinct profiles)")
    print("=" * 60)

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        users = conn.execute(text("SELECT id, email FROM users")).mappings().all()
        user_map = {u["email"]: u["id"] for u in users}

        if "runner.taipei@runsense.demo" not in user_map:
            print("runner.taipei@runsense.demo not found, running seed_demo_personas first...")
            from scripts.seed_demo_personas import seed_demo_personas
            seed_demo_personas()
            users = conn.execute(text("SELECT id, email FROM users")).mappings().all()
            user_map = {u["email"]: u["id"] for u in users}

        now_utc = datetime.now(timezone.utc)

        for email, schedule in _ATHLETE_SCHEDULES.items():
            if email not in user_map:
                print(f"  skip {email}: no such user")
                continue
            user_id = user_map[email]
            tz_name, utc_hour = _TIMEZONE_BY_EMAIL[email]
            # Anchor "today" to the athlete's own local date, matching how
            # TrainingPlanService/training_load/trend pick the current row --
            # a naive UTC "today" can already be yesterday for Taipei/Tokyo
            # (UTC+8/+9), leaving the row the app actually reads for "today"
            # one calendar day outside recompute_training_load's fixed
            # changed_date..changed_date+27 window and stale.
            today = now_utc.astimezone(ZoneInfo(tz_name)).date()
            print(f"\nSeeding {len(schedule)} activities for {email} ({user_id})...")
            lock_athlete_training_load(conn, user_id)

            max_offset = max(offset for offset, *_ in schedule)
            start_date = today - timedelta(days=max_offset)
            deleted = conn.execute(
                _DELETE_BASELINE_IN_RANGE,
                {"athlete_id": user_id, "start_date": start_date, "end_date": today},
            ).rowcount
            if deleted:
                print(f"  -> Removed {deleted} overlapping demo-seed baseline row(s) in range")
            stale = conn.execute(_DELETE_ALL_RICH_SEED, {"athlete_id": user_id}).rowcount
            if stale:
                print(f"  -> Removed {stale} stale rich-seed row(s) from a prior schedule")

            earliest_date = today
            for offset, duration, rpe, dist, avg_hr, max_hr, avg_cad, max_cad, elev_gain, calories, te, te_label, title in schedule:
                act_date = today - timedelta(days=offset)
                earliest_date = min(earliest_date, act_date)
                performed_at = datetime(act_date.year, act_date.month, act_date.day, utc_hour, 30, tzinfo=timezone.utc)
                mutation_id = uuid.uuid5(uuid.NAMESPACE_URL, f"rich-seed:{email}:{act_date.isoformat()}")

                session_load = Decimal(duration * rpe)

                device_metrics_dict = {
                    "avgHeartRate": avg_hr,
                    "maxHeartRate": max_hr,
                    "avgCadenceStepsPerMin": avg_cad,
                    "maxCadenceStepsPerMin": max_cad,
                    "elevationGainM": elev_gain,
                    "calories": calories,
                    "aerobicTrainingEffect": te,
                    "trainingEffectLabel": te_label,
                }

                conn.execute(
                    text(
                        """
                        INSERT INTO completed_activities (
                            athlete_id, client_mutation_id, request_fingerprint,
                            duration_minutes, rpe, performed_at,
                            timezone_snapshot, local_training_date, session_load,
                            distance_km, device_metrics, provider
                        ) VALUES (
                            :athlete_id, :client_mutation_id, :request_fingerprint,
                            :duration_minutes, :rpe, :performed_at,
                            :timezone_snapshot, :local_training_date, :session_load,
                            :distance_km, CAST(:device_metrics AS jsonb), 'garmin'
                        )
                        ON CONFLICT (athlete_id, client_mutation_id) DO UPDATE
                        SET duration_minutes = EXCLUDED.duration_minutes,
                            rpe = EXCLUDED.rpe,
                            session_load = EXCLUDED.session_load,
                            distance_km = EXCLUDED.distance_km,
                            device_metrics = EXCLUDED.device_metrics,
                            provider = EXCLUDED.provider,
                            local_training_date = EXCLUDED.local_training_date
                        """
                    ),
                    {
                        "athlete_id": user_id,
                        "client_mutation_id": str(mutation_id),
                        "request_fingerprint": f"rich-seed:{mutation_id}",
                        "duration_minutes": duration,
                        "rpe": rpe,
                        "performed_at": performed_at,
                        "timezone_snapshot": tz_name,
                        "local_training_date": act_date,
                        "session_load": session_load,
                        "distance_km": Decimal(str(dist)),
                        "device_metrics": json.dumps(device_metrics_dict),
                    },
                )

            print(f"  -> Recomputing training load from {earliest_date} to {today}...")
            recompute_training_load(conn, user_id, earliest_date)
            # recompute_training_load only materializes changed_date..changed_date+27.
            # earliest_date+27 can land before "today" by the time an athlete's local
            # date has rolled past the UTC date this script ran under (or simply
            # because the schedule's earliest offset is < 27) -- recompute again
            # anchored on today so today's own row (and the trailing 28-day window
            # ending on it) reflects the schedule just inserted, not a stale row
            # left over from an earlier run.
            if today != earliest_date:
                recompute_training_load(conn, user_id, today)

    print("\nDatabase seeded successfully!")


if __name__ == "__main__":
    seed_rich_history()

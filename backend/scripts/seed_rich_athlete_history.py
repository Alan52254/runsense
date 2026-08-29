"""Seed realistic 28-day Garmin activities and training loads for Taipei & all demo athletes."""

from __future__ import annotations

import os
import sys
import uuid
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path

# Force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text
from app.training_load_store import lock_athlete_training_load, recompute_training_load

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/runsense")


def seed_rich_history():
    print("=" * 60)
    print("Seeding 28-Day Rich Training History for Taipei & Demo Athletes")
    print("=" * 60)

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        # Get users
        users = conn.execute(text("SELECT id, email FROM users")).mappings().all()
        user_map = {u["email"]: u["id"] for u in users}

        if "runner.taipei@runsense.demo" not in user_map:
            print("runner.taipei@runsense.demo not found, running seed_demo_personas first...")
            from scripts.seed_demo_personas import seed_demo_personas
            seed_demo_personas()
            users = conn.execute(text("SELECT id, email FROM users")).mappings().all()
            user_map = {u["email"]: u["id"] for u in users}

        today = datetime.now(timezone.utc).date()

        # Training patterns over last 28 days designed with realistic physiological metrics
        # (day_offset, duration_min, rpe, distance_km, avg_hr, max_hr, avg_cad, max_cad, elev_gain, calories, te, te_label, title)
        training_schedule = [
            (1, 45, 6, 8.2, 154, 168, 178, 186, 35, 510, 3.6, "TEMPO", "大安森林公園漸進配速跑"),
            (2, 35, 4, 6.0, 136, 148, 174, 180, 15, 380, 2.7, "AEROBIC_BASE", "河濱輕鬆有氧跑"),
            (3, 50, 7, 10.0, 165, 182, 176, 184, 160, 640, 4.1, "THRESHOLD", "劍南路丘陵肌耐力跑"),
            (5, 40, 5, 7.5, 158, 172, 180, 188, 12, 470, 3.8, "TEMPO", "田徑場節奏跑 (Tempo Run)"),
            (6, 60, 6, 12.0, 144, 158, 176, 182, 45, 750, 3.5, "AEROBIC_BASE", "基隆河濱長距離慢跑 (LSD)"),
            (7, 30, 3, 5.2, 126, 138, 172, 178, 8, 290, 2.0, "RECOVERY", "恢復慢跑 (Active Recovery)"),
            (9, 45, 7, 8.5, 168, 186, 184, 194, 20, 580, 4.3, "VO2MAX", "間歇訓練 800m x 5"),
            (10, 35, 4, 6.0, 134, 145, 174, 180, 14, 370, 2.6, "AEROBIC_BASE", "輕鬆排乳酸跑"),
            (12, 55, 6, 11.0, 152, 166, 178, 184, 40, 680, 3.7, "TEMPO", "配速巡航跑"),
            (14, 40, 5, 7.0, 140, 152, 176, 182, 22, 440, 3.1, "AEROBIC_BASE", "有氧基礎跑"),
            (15, 65, 6, 13.5, 146, 162, 176, 182, 55, 840, 3.8, "AEROBIC_BASE", "週末半馬模擬長距離"),
            (17, 35, 3, 5.8, 128, 140, 172, 178, 10, 330, 2.2, "RECOVERY", "動態恢復跑"),
            (19, 50, 6, 9.5, 150, 165, 178, 184, 30, 600, 3.6, "TEMPO", "金山南路定速跑"),
            (21, 40, 4, 7.2, 138, 150, 174, 180, 18, 430, 2.9, "AEROBIC_BASE", "傍晚微風有氧"),
            (23, 45, 7, 8.0, 167, 185, 182, 192, 15, 560, 4.2, "VO2MAX", "亞索 800 間歇"),
            (25, 30, 3, 5.0, 122, 134, 170, 176, 6, 260, 1.8, "RECOVERY", "超慢跑輕鬆動一動"),
            (27, 55, 5, 10.5, 142, 156, 176, 182, 35, 660, 3.4, "AEROBIC_BASE", "中距離耐力維持跑"),
        ]

        for email, user_id in user_map.items():
            print(f"\nSeeding {len(training_schedule)} activities for {email} ({user_id})...")
            lock_athlete_training_load(conn, user_id)
            earliest_date = today

            for offset, duration, rpe, dist, avg_hr, max_hr, avg_cad, max_cad, elev_gain, calories, te, te_label, title in training_schedule:
                act_date = today - timedelta(days=offset)
                earliest_date = min(earliest_date, act_date)
                performed_at = datetime(act_date.year, act_date.month, act_date.day, 6, 30, tzinfo=timezone.utc)
                mutation_id = uuid.uuid5(uuid.NAMESPACE_URL, f"rich-seed:{email}:{act_date.isoformat()}")

                session_load = Decimal(duration * rpe)

                device_metrics_dict = {
                    "avg_heart_rate": avg_hr,
                    "max_heart_rate": max_hr,
                    "avg_cadence_steps_per_min": avg_cad,
                    "max_cadence_steps_per_min": max_cad,
                    "elevation_gain_m": elev_gain,
                    "calories": calories,
                    "aerobic_training_effect": te,
                    "training_effect_label": te_label,
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
                            'Asia/Taipei', :local_training_date, :session_load,
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
                        "request_fingerprint": f"rich-fp-{act_date.isoformat()}",
                        "duration_minutes": duration,
                        "rpe": rpe,
                        "performed_at": performed_at,
                        "local_training_date": act_date,
                        "session_load": session_load,
                        "distance_km": Decimal(str(dist)),
                        "device_metrics": json.dumps(device_metrics_dict),
                    },
                )

            print(f"  -> Recomputing training load from {earliest_date} to {today}...")
            recompute_training_load(conn, user_id, earliest_date)

    print("\nDatabase seeded successfully!")


if __name__ == "__main__":
    seed_rich_history()

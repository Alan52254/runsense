"""Seed competition-only demo users and athlete profiles.

Run manually from backend/; application code never imports this module.
"""

from __future__ import annotations

import os

import bcrypt
from sqlalchemy import create_engine, text


PERSONAS = (
    ("runner.taipei@runsense.demo", "TaipeiDemo!2026", "Asia/Taipei"),
    ("runner.tokyo@runsense.demo", "TokyoDemo!2026", "Asia/Tokyo"),
    ("runner.london@runsense.demo", "LondonDemo!2026", "Europe/London"),
)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to seed demo personas")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            for email, password, timezone_name in PERSONAS:
                password_hash = bcrypt.hashpw(
                    password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")
                user_id = conn.execute(
                    text(
                        """
                        INSERT INTO users (email, password_hash)
                        VALUES (:email, :password_hash)
                        ON CONFLICT (email) DO UPDATE
                        SET password_hash = EXCLUDED.password_hash
                        RETURNING id
                        """
                    ),
                    {"email": email, "password_hash": password_hash},
                ).scalar_one()
                conn.execute(
                    text(
                        """
                        INSERT INTO athlete_profiles (user_id, timezone)
                        VALUES (:user_id, :timezone)
                        ON CONFLICT (user_id) DO UPDATE
                        SET timezone = EXCLUDED.timezone, updated_at = now()
                        """
                    ),
                    {"user_id": user_id, "timezone": timezone_name},
                )
    finally:
        engine.dispose()

    print(f"Seeded {len(PERSONAS)} competition demo personas.")


if __name__ == "__main__":
    main()

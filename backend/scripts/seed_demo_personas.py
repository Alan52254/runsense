"""Seed competition-only demo users, athlete profiles, and one demo Team.

Run manually from backend/; application code never imports this module.

The web coach screens (docs/mvp-checklist.md Item 1) need *some* coach with
*some* roster to demo against locally, and there is no team/consent seed
data path yet (that's Item 2's `PATCH /me/consent-grants`, not built by this
change). So this script -- the existing, established place demo identities
already get seeded -- additionally makes the Taipei persona a head_coach of
one demo Team, with the Tokyo and London personas as its athlete members,
some Consent Scopes granted, and enough Completed Activities to materialize
real Training Load Trend numbers via the same recompute path
`POST /activities` uses. Everything here is idempotent, matching the
existing users/athlete_profiles ON CONFLICT pattern.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import bcrypt
from sqlalchemy import Connection, create_engine, text

from app.training_load_store import lock_athlete_training_load, recompute_training_load

PERSONAS = (
    ("runner.taipei@runsense.demo", "TaipeiDemo!2026", "Asia/Taipei", "臺北教練", "Taipei"),
    ("runner.tokyo@runsense.demo", "TokyoDemo!2026", "Asia/Tokyo", "東京選手", "Tokyo"),
    ("runner.london@runsense.demo", "LondonDemo!2026", "Europe/London", "倫敦選手", "London"),
)

DEMO_TEAM_NAME = "臺北長跑訓練隊"

# (email, granted consent scopes for DEMO_TEAM_NAME)
DEMO_CONSENTS = {
    "runner.tokyo@runsense.demo": ["activity_summary", "training_load", "injury_status"],
    "runner.london@runsense.demo": [
        "activity_summary",
        "training_load",
        "injury_status",
        "injury_detail",
    ],
}

_ALL_SCOPES = ("activity_summary", "training_load", "injury_status", "injury_detail")

_INSERT_ACTIVITY = text(
    """
    INSERT INTO completed_activities (
        athlete_id, client_mutation_id, request_fingerprint,
        duration_minutes, rpe, performed_at,
        timezone_snapshot, local_training_date, session_load
    ) VALUES (
        :athlete_id, :client_mutation_id, :request_fingerprint,
        :duration_minutes, :rpe, :performed_at,
        :timezone_snapshot, :local_training_date, :session_load
    )
    ON CONFLICT (athlete_id, client_mutation_id) DO NOTHING
    """
)


def _seed_users(conn: Connection) -> dict[str, uuid.UUID]:
    user_ids: dict[str, uuid.UUID] = {}
    for email, password, timezone_name, display_name, city in PERSONAS:
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user_id = conn.execute(
            text(
                """
                INSERT INTO users (email, password_hash, display_name)
                VALUES (:email, :password_hash, :display_name)
                ON CONFLICT (email) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    display_name = EXCLUDED.display_name
                RETURNING id
                """
            ),
            {"email": email, "password_hash": password_hash, "display_name": display_name},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO athlete_profiles (user_id, timezone, city)
                VALUES (:user_id, :timezone, :city)
                ON CONFLICT (user_id) DO UPDATE
                SET timezone = EXCLUDED.timezone, city = EXCLUDED.city, updated_at = now()
                """
            ),
            {"user_id": user_id, "timezone": timezone_name, "city": city},
        )
        user_ids[email] = user_id
    return user_ids


def _seed_team(conn: Connection, user_ids: dict[str, uuid.UUID]) -> uuid.UUID:
    team_id = conn.execute(
        text(
            """
            INSERT INTO teams (name) VALUES (:name)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ),
        {"name": DEMO_TEAM_NAME},
    ).scalar_one()

    coach_id = user_ids["runner.taipei@runsense.demo"]
    conn.execute(
        text(
            """
            INSERT INTO team_memberships (team_id, user_id, role, status, joined_at)
            VALUES (:team_id, :user_id, 'head_coach', 'ACTIVE', now())
            ON CONFLICT (team_id, user_id) DO UPDATE
            SET role = EXCLUDED.role, status = EXCLUDED.status
            """
        ),
        {"team_id": team_id, "user_id": coach_id},
    )

    for email in DEMO_CONSENTS:
        athlete_id = user_ids[email]
        conn.execute(
            text(
                """
                INSERT INTO team_memberships (team_id, user_id, role, status, joined_at)
                VALUES (:team_id, :user_id, 'athlete', 'ACTIVE', now())
                ON CONFLICT (team_id, user_id) DO UPDATE
                SET role = EXCLUDED.role, status = EXCLUDED.status
                """
            ),
            {"team_id": team_id, "user_id": athlete_id},
        )
        granted_scopes = set(DEMO_CONSENTS[email])
        for scope in _ALL_SCOPES:
            conn.execute(
                text(
                    """
                    INSERT INTO consent_grants (team_id, athlete_id, scope, granted, changed_at)
                    VALUES (:team_id, :athlete_id, :scope, :granted, now())
                    ON CONFLICT (team_id, athlete_id, scope) DO UPDATE
                    SET granted = EXCLUDED.granted, changed_at = now()
                    """
                ),
                {
                    "team_id": team_id,
                    "athlete_id": athlete_id,
                    "scope": scope,
                    "granted": scope in granted_scopes,
                },
            )
    return team_id


def _seed_sample_activities(conn: Connection, user_ids: dict[str, uuid.UUID]) -> None:
    """A handful of Completed Activities per demo athlete, materialized into
    training_load_daily via the same recompute path POST /activities uses --
    so the roster's acute/chronic/ratio/data_quality numbers are real, not
    hand-inserted training_load_daily rows that could drift from
    app.training_load's own rules."""

    today = datetime.now(timezone.utc).date()
    for email in DEMO_CONSENTS:
        athlete_id = user_ids[email]
        # an athlete whose real Garmin history has been imported
        # (import_garmin_fit_telemetry.py) must not get placeholder rows
        # back on the next start-up: they would double-count against real
        # runs and put made-up sessions in a real history
        has_real_history = conn.execute(
            text("SELECT 1 FROM completed_activities WHERE athlete_id = :a AND provider = 'garmin' "
                 "AND (request_fingerprint LIKE 'garmin-import:%' "
                 "OR request_fingerprint LIKE 'simulated-partner:%') LIMIT 1"),
            {"a": athlete_id},
        ).first()
        if has_real_history:
            continue
        lock_athlete_training_load(conn, athlete_id)
        last_date: date | None = None
        for offset in (1, 3, 5, 8, 11, 14, 18, 22):
            activity_date = today - timedelta(days=offset)
            performed_at = datetime(
                activity_date.year, activity_date.month, activity_date.day, 8, 0, tzinfo=timezone.utc
            )
            duration_minutes = Decimal(30 + (offset % 4) * 10)
            rpe = 4 + (offset % 5)
            client_mutation_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"runsense-demo-seed:{email}:{activity_date.isoformat()}"
            )
            conn.execute(
                _INSERT_ACTIVITY,
                {
                    "athlete_id": athlete_id,
                    "client_mutation_id": client_mutation_id,
                    "request_fingerprint": f"demo-seed:{client_mutation_id}",
                    "duration_minutes": duration_minutes,
                    "rpe": rpe,
                    "performed_at": performed_at,
                    "timezone_snapshot": "Asia/Taipei",
                    "local_training_date": activity_date,
                    "session_load": duration_minutes * rpe,
                },
            )
            last_date = activity_date if last_date is None else min(last_date, activity_date)
        if last_date is not None:
            recompute_training_load(conn, athlete_id, last_date)


def _seed_sample_injuries(conn: Connection, user_ids: dict[str, uuid.UUID]) -> None:
    """Seed one current report per athlete so both consent scopes are visible
    in the coach demo without weakening the runtime RLS policies."""

    samples = {
        "runner.tokyo@runsense.demo": ("MILD", "左膝", "下坡時略緊，平路正常。"),
        "runner.london@runsense.demo": ("MODERATE", "右小腿", "熱身後仍有拉扯感，今天改做低強度。"),
    }
    reported_at = datetime.now(timezone.utc) - timedelta(days=1)
    timezone_by_email = {email: timezone_name for email, _, timezone_name, _, _ in PERSONAS}

    for email, (severity, body_part, free_text) in samples.items():
        athlete_id = user_ids[email]
        mutation_id = uuid.uuid5(uuid.NAMESPACE_URL, f"runsense-demo-injury:{email}")
        report_id = conn.execute(
            text(
                """
                INSERT INTO injury_reports (
                    athlete_id, client_mutation_id, request_fingerprint,
                    has_issue, severity_band, body_part, reported_at,
                    timezone_snapshot, local_training_date
                ) VALUES (
                    :athlete_id, :client_mutation_id, :request_fingerprint,
                    true, :severity_band, :body_part, :reported_at,
                    :timezone_snapshot, :local_training_date
                )
                ON CONFLICT (athlete_id, client_mutation_id) DO UPDATE
                SET severity_band = EXCLUDED.severity_band,
                    body_part = EXCLUDED.body_part,
                    reported_at = EXCLUDED.reported_at,
                    timezone_snapshot = EXCLUDED.timezone_snapshot,
                    local_training_date = EXCLUDED.local_training_date
                RETURNING id
                """
            ),
            {
                "athlete_id": athlete_id,
                "client_mutation_id": mutation_id,
                "request_fingerprint": mutation_id.hex * 2,
                "severity_band": severity,
                "body_part": body_part,
                "reported_at": reported_at,
                "timezone_snapshot": timezone_by_email[email],
                "local_training_date": reported_at.astimezone(ZoneInfo(timezone_by_email[email])).date(),
            },
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO injury_report_details (injury_report_id, free_text)
                VALUES (:report_id, :free_text)
                ON CONFLICT (injury_report_id) DO UPDATE
                SET free_text = EXCLUDED.free_text
                """
            ),
            {"report_id": report_id, "free_text": free_text},
        )


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to seed demo personas")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            user_ids = _seed_users(conn)
            _seed_team(conn, user_ids)
            _seed_sample_activities(conn, user_ids)
            _seed_sample_injuries(conn, user_ids)
    finally:
        engine.dispose()

    print(
        f"Seeded {len(PERSONAS)} competition demo personas, 1 demo team "
        f"({DEMO_TEAM_NAME}), sample training load, and body-status reports."
    )


if __name__ == "__main__":
    main()

"""Reset the competition demo to one known, repeatable state.

    python -m scripts.reset_competition_demo        # from backend/

Touches only the demo team (seed_demo_personas.DEMO_TEAM_NAME) and its three
personas. It:

1. clears the team's chat (messages, cards, read marks), schedule drafts,
   assignment batches, Assigned Workouts and review decisions, and the
   athletes' health-coach proposals -- the leftovers of rehearsals;
2. re-seeds the personas, team, consents and body reports
   (seed_demo_personas: London's 右小腿 report is dated yesterday);
3. carries London's (simulated) training forward to yesterday, so the
   suggested week has recent load to work from;
4. puts one coach-assigned interval session on London's day after tomorrow,
   so the week shows the injury asking the coach to lighten the coach's
   own session.

Tokyo keeps its real Garmin history (to 2026-08-22): its suggested week is
left to the coach, which is what the system should do with no recent data.

Run against the demo database only; it deletes rows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from app import assignment_service
from scripts import seed_demo_personas

COACH = "runner.taipei@runsense.demo"
LONDON = "runner.london@runsense.demo"


def _clear(conn, team_id) -> dict[str, int]:
    rooms = "SELECT id FROM chat_rooms WHERE team_id = :t"
    athletes = "SELECT user_id FROM team_memberships WHERE team_id = :t AND role = 'athlete'"
    counts = {}
    for label, sql in (
        # children before parents: decisions and assignments point at
        # batches, batches at cards, cards at messages
        ("decisions", "DELETE FROM assignment_decisions WHERE team_id = :t"),
        ("assigned_workouts", "DELETE FROM assigned_workouts WHERE team_id = :t"),
        ("assignment_batches", "DELETE FROM assignment_batches WHERE team_id = :t"),
        ("chat_reads", f"DELETE FROM chat_reads WHERE room_id IN ({rooms})"),
        ("chat_cards", f"DELETE FROM chat_cards WHERE room_id IN ({rooms})"),
        ("chat_messages", f"DELETE FROM chat_messages WHERE room_id IN ({rooms})"),
        ("coach_proposals", f"DELETE FROM coach_proposals WHERE athlete_id IN ({athletes})"),
    ):
        counts[label] = conn.execute(text(sql), {"t": team_id}).rowcount
    return counts


def main() -> None:
    if os.environ.get("COMPETITION_DEMO_ONLY", "").lower() != "true":
        raise RuntimeError("Refusing to reset: COMPETITION_DEMO_ONLY must be true")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        team_id = conn.execute(text("SELECT id FROM teams WHERE name = :n"),
                               {"n": seed_demo_personas.DEMO_TEAM_NAME}).scalar_one_or_none()
        if team_id is not None:
            print("cleared:", _clear(conn, team_id))

    seed_demo_personas.main()

    london_today = datetime.now(UTC).astimezone(ZoneInfo("Europe/London")).date()
    subprocess.run([sys.executable, "-m", "scripts.seed_taipei_recent_activities", "--email", LONDON,
                    "--timezone", "Europe/London",
                    "--start", (london_today - timedelta(days=60)).isoformat(),
                    "--end", (london_today - timedelta(days=1)).isoformat()],
                   check=True, stdout=subprocess.DEVNULL)

    with engine.begin() as conn:
        ids = dict(conn.execute(text("SELECT email, id FROM users WHERE email IN (:c, :l)"),
                                {"c": COACH, "l": LONDON}).all())
        team_id = conn.execute(text("SELECT id FROM teams WHERE name = :n"),
                               {"n": seed_demo_personas.DEMO_TEAM_NAME}).scalar_one()
        day = london_today + timedelta(days=2)
        assignment_service.publish(
            conn, actor_id=ids[COACH], team_id=team_id, source="manual_assignment",
            days=[assignment_service.DayWrite(ids[LONDON], "倫敦選手", day, ({
                "title": "6 × 1000m @ 3:50/km，休 2 分", "duration_minutes": 60, "intensity_label": "間歇",
                "structure": [], "tracked": True, "notes": None},))])
    engine.dispose()
    print(f"Demo reset. London: training to {london_today - timedelta(days=1)}, "
          f"body report yesterday, coach intervals on {day}.")


if __name__ == "__main__":
    main()

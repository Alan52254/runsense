from datetime import date

from scripts.seed_taipei_recent_activities import build_plan


def test_recent_demo_plan_provides_a_complete_28_day_training_window():
    start = date(2026, 9, 18)
    end = date(2026, 10, 14)

    plan = build_plan(start, end, tag="tokyo-gapfill")
    recorded_days = {day for day, _title, _session in plan}

    assert len(recorded_days) >= 21
    assert end in recorded_days
    assert all(start <= day <= end for day in recorded_days)
    assert all(session.avg_hr > 0 and session.max_hr >= session.avg_hr for _, _, session in plan)
    assert all(session.segments for _, _, session in plan)

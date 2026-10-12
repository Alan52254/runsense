"""Re-run every saved workout analysis with the current analysis rules.

Run manually from backend/ (application code never imports this module),
after scripts/backfill_history_metrics.py --redetect:

    python scripts/recompute_workout_analyses.py [--email runner.tokyo@runsense.demo] [--dry-run]

Each analysis goes through the same route function the app calls when the
athlete presses 分析 (app/routes/workout_analysis.analyse), with the
segments the athlete confirmed. One correction is carried over from the
current detection: a work segment that the old detection stretched to the
watch's stop button (same start, ending at most TIMER_SNAP_S later than
the current detection says) takes the current end, and the seconds after
it become the cool-down. Sessions are processed oldest first, so each one
is compared with already-recomputed earlier sessions.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime_env import load_runtime_environment  # noqa: E402

load_runtime_environment()

from app.routes.workout_analysis import AnalyseRequest, analyse  # noqa: E402
from app.workout_segmentation import MIN_SEGMENT_S, TIMER_SNAP_S  # noqa: E402

_SAVED = text(
    """SELECT w.activity_id, w.athlete_id, w.session_type, w.segments, w.target_pace_s_per_km,
              t.auto_detection, ((t.samples->'t'->>-1)::int + 1) AS n, a.local_training_date
         FROM workout_analyses w
         JOIN activity_telemetry t ON t.activity_id = w.activity_id
         JOIN completed_activities a ON a.id = w.activity_id
         JOIN users u ON u.id = w.athlete_id
        WHERE (CAST(:email AS text) IS NULL OR u.email = :email)
        ORDER BY a.local_training_date, a.performed_at""")


class _Actor:
    def __init__(self, actor_id: uuid.UUID) -> None:
        self._id = str(actor_id)

    def get_current_actor_id(self) -> str:
        return self._id


def corrected_segments(saved: list[dict], detected: list[dict], n: int) -> tuple[list[dict], list[str]]:
    """The athlete's segments, with a stop-button stretch on a work segment
    undone where the current detection ends that same rep earlier."""
    segs = [dict(s) for s in saved]
    notes = []
    new_end = {s["start_s"]: s["end_s"] for s in detected if s["role"] == "work"}
    for i, s in enumerate(segs):
        end = new_end.get(s["start_s"])
        if s["role"] != "work" or end is None or not (0 < s["end_s"] - end <= TIMER_SNAP_S):
            continue
        old_end = s["end_s"]
        s["end_s"] = end
        notes.append(f"work {s['start_s']}-{old_end} -> {s['start_s']}-{end}")
        if i + 1 < len(segs) and segs[i + 1]["start_s"] == old_end:
            segs[i + 1]["start_s"] = end
        elif n - end >= MIN_SEGMENT_S:
            segs.insert(i + 1, {"role": "cooldown", "start_s": end, "end_s": n})
    return segs, notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    engine = create_engine(database_url, future=True)
    with engine.connect() as conn:
        rows = conn.execute(_SAVED, {"email": args.email}).all()
        conn.rollback()
        for r in rows:
            detected = (r.auto_detection or {}).get("segments") or []
            segs, notes = corrected_segments(r.segments, detected, r.n)
            label = f"{r.local_training_date} {r.session_type}"
            if args.dry_run:
                print(label, "|", "; ".join(notes) or "segments unchanged")
                continue
            payload = AnalyseRequest(segments=segs, session_type=r.session_type,
                                     target_pace_s_per_km=float(r.target_pace_s_per_km)
                                     if r.target_pace_s_per_km else None)
            result = analyse(r.activity_id, payload, conn, _Actor(r.athlete_id))
            print(label, "|", "; ".join(notes) or "segments unchanged", "|",
                  f"{len(result['findings'])} findings, narrative: {result['narrative_source']}", flush=True)


if __name__ == "__main__":
    main()

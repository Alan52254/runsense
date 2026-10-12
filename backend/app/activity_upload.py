"""In-app .fit upload: one recorded run in -- a Completed Activity with its
telemetry, matched to the coach's Assigned Workout it completed, and
announced by the RunSense helper in the athlete's chat room with each coach.

Decided with the athlete on 2026-10-11:

- RPE is required: training load is duration x RPE, and a .fit file carries
  none (scripts/import_garmin_activities.py skips runs without one too).
- A file whose run already exists (same start second) is refused.
- Matching: the same day's unfinished assignment of the same type (an
  interval session for an interval workout, an easy run for an easy one);
  otherwise, within MATCH_WINDOW_DAYS either side, an unfinished interval
  workout with exactly the reps and distances that were run, the nearest
  date first; otherwise none (training of the athlete's own). A warm-up or
  cool-down recorded on its own is never matched. The athlete can correct
  the match in History (routes/activity_upload.py).
- Every upload is announced, in every team whose coach the athlete shares
  'activity_summary' with -- and only there: without that scope the coach
  could not open the data anyway, and the message itself would tell them
  when and how far the athlete ran.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

from app import chat_service, workout_prescription
from app.activity_structure import moving_median_speed, structure_from_detection
from app.fit_telemetry import parse_fit, peak_rolling_hr
from app.training_load_store import lock_athlete_training_load, recompute_training_load
from app.workout_analysis import analyse_workout, fmt_pace, history_summary, resolve_hr_profile
from app.workout_narrative import signature_label
from app.workout_segmentation import detect_workout

MATCH_WINDOW_DAYS = 3
# a data-quality setting: a run's .fit file is well under 5 MB
MAX_FIT_BYTES = 20 * 1024 * 1024

_KIND_TO_SESSION = {"intervals": "intervals", "tempo": "tempo", "continuous": "easy"}
_WORKOUT_KINDS = ("intervals", "tempo")
_WEEKDAY = "一二三四五六日"
_ROLE_LABEL = {"main": "訓練", "run": "訓練", "warmup": "暖身", "cooldown": "收操"}


class UploadRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_INSERT_ACTIVITY = text(
    """
    INSERT INTO completed_activities (
        athlete_id, client_mutation_id, request_fingerprint, provider, provider_activity_id,
        duration_minutes, rpe, performed_at, timezone_snapshot, local_training_date, session_load,
        distance_km, device_metrics, structure
    ) VALUES (
        :a, :cmid, :fp, 'garmin', NULL, :minutes, :rpe, :at, :tz, :d, :load, :km,
        CAST(:metrics AS jsonb), '[]'::jsonb
    )
    ON CONFLICT (athlete_id, client_mutation_id) DO UPDATE SET
        deleted_at = NULL, rpe = EXCLUDED.rpe, session_load = EXCLUDED.session_load
    RETURNING id
    """
)

_INSERT_TELEMETRY = text(
    """
    INSERT INTO activity_telemetry (
        activity_id, athlete_id, source, sport, sub_sport, device, hr_profile, laps, timer_events,
        workout_steps, samples, hr_peak_30s, activity_name, auto_detection, auto_summary
    ) VALUES (
        :id, :a, 'garmin_fit', :sport, :sub, :device, CAST(:hr AS jsonb), CAST(:laps AS jsonb),
        CAST(:events AS jsonb), CAST(:steps AS jsonb), CAST(:samples AS jsonb), :peak, :name,
        CAST(:det AS jsonb), CAST(:summ AS jsonb)
    )
    ON CONFLICT (activity_id) DO UPDATE SET
        samples = EXCLUDED.samples, laps = EXCLUDED.laps, timer_events = EXCLUDED.timer_events,
        auto_detection = EXCLUDED.auto_detection, auto_summary = EXCLUDED.auto_summary
    """
)


def _device_metrics(session: dict[str, Any]) -> dict[str, Any]:
    """The Garmin import's keys (scripts/import_garmin_fit_telemetry.py);
    a .fit session's running cadence counts one foot, so it is doubled."""
    m: dict[str, Any] = {}
    if session.get("avg_hr") is not None:
        m["avgHeartRate"] = round(session["avg_hr"])
    if session.get("max_hr") is not None:
        m["maxHeartRate"] = round(session["max_hr"])
    if session.get("avg_cadence"):
        m["avgCadenceStepsPerMin"] = round(session["avg_cadence"] * 2)
    if session.get("max_cadence"):
        m["maxCadenceStepsPerMin"] = round(session["max_cadence"] * 2)
    if session.get("ascent_m") is not None:
        m["elevationGainM"] = round(float(session["ascent_m"]), 1)
    if session.get("descent_m") is not None:
        m["elevationLossM"] = round(float(session["descent_m"]), 1)
    if session.get("calories") is not None:
        m["calories"] = round(session["calories"])
    return m


def _easy_speed(tx: Connection, athlete_id: uuid.UUID) -> float | None:
    """The athlete's easy pace, as the importer computes it: median moving
    speed of their continuous runs."""
    speeds = [s for s in tx.execute(text(
        """SELECT (auto_summary->>'moving_median_speed')::float FROM activity_telemetry
            WHERE athlete_id = :a AND auto_summary->>'kind' = 'continuous'"""), {"a": athlete_id}).scalars() if s]
    return statistics.median(speeds) if speeds else None


def _day_role(tx: Connection, athlete_id: uuid.UUID, activity_id: uuid.UUID, on: date, at, kind: str) -> str:
    """main for a workout; for an easy run, warm-up / cool-down around the
    day's workout when there is one, else a run of its own."""
    if kind in _WORKOUT_KINDS:
        return "main"
    main_at = tx.execute(text(
        """SELECT a.performed_at FROM completed_activities a JOIN activity_telemetry t ON t.activity_id = a.id
            WHERE a.athlete_id = :a AND a.local_training_date = :d AND a.deleted_at IS NULL AND a.id <> :id
              AND t.auto_summary->>'kind' IN ('intervals', 'tempo')
            ORDER BY a.distance_km DESC NULLS LAST LIMIT 1"""),
        {"a": athlete_id, "d": on, "id": activity_id}).scalar_one_or_none()
    if main_at is None:
        return "run"
    return "warmup" if at < main_at else "cooldown"


def assignment_type(structure: list[dict] | None) -> str:
    """workout when the coach set an interval / tempo block, else easy."""
    return "workout" if any(seg.get("kind") == "interval" for seg in structure or []) else "easy"


def _prescribed_distances(row: Any) -> list[int | None]:
    p = workout_prescription.from_assignment(row.structure or [], row.title)
    return [r.get("distance_m") for r in workout_prescription.expand(p)] if p else []


_CANDIDATES = text(
    """
    SELECT w.id, w.local_date, w.title, w.structure, w.created_at, w.status, c.activity_id AS completed_by
      FROM assigned_workouts w
      LEFT JOIN assignment_completions c ON c.assigned_workout_id = w.id
     WHERE w.athlete_id = :a AND w.tracked AND w.local_date BETWEEN :lo AND :hi
     ORDER BY w.local_date, w.created_at DESC
    """
)


def candidates(tx: Connection, athlete_id: uuid.UUID, on: date, activity_id: uuid.UUID | None = None) -> list[Any]:
    """Assignments within MATCH_WINDOW_DAYS of `on` this run may complete:
    not completed yet (stored COMPLETED or linked to another run)."""
    rows = tx.execute(_CANDIDATES, {"a": athlete_id, "lo": on - timedelta(days=MATCH_WINDOW_DAYS),
                                     "hi": on + timedelta(days=MATCH_WINDOW_DAYS)}).all()
    return [r for r in rows
            if (r.completed_by == activity_id if r.completed_by is not None else r.status != "COMPLETED")]


def match_assignment(tx: Connection, athlete_id: uuid.UUID, activity_id: uuid.UUID, on: date,
                     detection: dict, reps_m: list[int | None]) -> Any | None:
    kind = "workout" if detection.get("kind") in _WORKOUT_KINDS else "easy"
    pool = candidates(tx, athlete_id, on)
    same_day = [r for r in pool if r.local_date == on and assignment_type(r.structure) == kind]
    if same_day:
        return same_day[0]
    if kind != "workout" or not reps_m:
        return None
    fits = [r for r in pool if r.local_date != on and assignment_type(r.structure) == "workout"
            and _prescribed_distances(r) == reps_m]
    if not fits:
        return None
    return min(fits, key=lambda r: (abs((r.local_date - on).days), r.local_date))


def link(tx: Connection, athlete_id: uuid.UUID, activity_id: uuid.UUID, on: date,
         assignment_id: uuid.UUID | None, linked_by: str) -> None:
    """Make `assignment_id` (or nothing) the assignment this run completed."""
    tx.execute(text("DELETE FROM assignment_completions WHERE activity_id = :id"), {"id": activity_id})
    if assignment_id is not None:
        tx.execute(text(
            """INSERT INTO assignment_completions (assigned_workout_id, activity_id, athlete_id,
                   activity_local_date, linked_by) VALUES (:w, :id, :a, :d, :by)"""),
            {"w": assignment_id, "id": activity_id, "a": athlete_id, "d": on, "by": linked_by})


def _md(d: date) -> str:
    return f"{d.month}/{d.day}（{_WEEKDAY[d.weekday()]}）"


def _announce(tx: Connection, athlete_id: uuid.UUID, activity_id: uuid.UUID, on: date, role: str,
              km: float | None, pace: float | None, label: str | None, assignment: Any | None) -> int:
    """One RunSense helper message per team whose coach may read the data."""
    teams = tx.execute(text(
        """SELECT m.team_id FROM team_memberships m
            WHERE m.user_id = :a AND m.role = 'athlete' AND m.status = 'ACTIVE'
              AND EXISTS (SELECT 1 FROM consent_grants g WHERE g.team_id = m.team_id AND g.athlete_id = :a
                           AND g.scope = 'activity_summary' AND g.granted)"""), {"a": athlete_id}).scalars().all()
    if not teams:
        return 0
    name = tx.execute(text("SELECT COALESCE(display_name, email) FROM users WHERE id = :a"),
                      {"a": athlete_id}).scalar_one()
    what = f"{km:g} km" if km else "一筆紀錄"
    if pace:
        what += f"、平均 {fmt_pace(pace)}"
    body = f"{name} 上傳了 {_md(on)}的{_ROLE_LABEL[role]}：{what}"
    if label:
        body += f"（{label}）"
    body += "。"
    if role in ("main", "run"):
        if assignment is None:
            body += "沒有對應的教練課表，記為自主訓練。"
        elif assignment.local_date == on:
            body += f"教練課表：{assignment.title}。"
        else:
            body += f"完成 {_md(assignment.local_date)}的教練課表：{assignment.title}（改在這天練）。"
    body += "可以點「查看數據」看分圈與課表分析。"
    payload = {"kind": "activity_uploaded", "activity_id": str(activity_id), "athlete_id": str(athlete_id),
               "date": on.isoformat(), "day_role": role, "distance_km": km, "pace_s_per_km": pace,
               "signature_label": label,
               "assignment": None if assignment is None else {
                   "id": str(assignment.id), "title": assignment.title, "date": assignment.local_date.isoformat()}}
    for team_id in teams:
        room = chat_service.ensure_room(tx, team_id, athlete_id)
        chat_service.post_message(tx, room, "ai", body, payload=payload)
    return len(teams)


def ingest_fit(tx: Connection, athlete_id: uuid.UUID, data: bytes, rpe: int, tz_name: str) -> dict[str, Any]:
    """The whole upload in one transaction; raises UploadRejected."""
    if len(data) > MAX_FIT_BYTES:
        raise UploadRejected("FIT_TOO_LARGE", "檔案太大")
    try:
        tele = parse_fit(data)
    except Exception as exc:  # FitParseError and any decoder failure alike
        raise UploadRejected("FIT_UNREADABLE", "讀不到這個 .fit 檔的跑步資料") from exc
    if tele.get("sport") != "running":
        raise UploadRejected("FIT_NOT_A_RUN", "這個檔案不是跑步紀錄")
    at = tele["start_time"]
    if tx.execute(text("SELECT 1 FROM completed_activities WHERE athlete_id = :a AND performed_at = :t "
                       "AND deleted_at IS NULL"), {"a": athlete_id, "t": at}).first():
        raise UploadRejected("ACTIVITY_ALREADY_EXISTS", "這次跑步已經有紀錄了")

    session = tele.get("session") or {}
    seconds = session.get("timer_s") or session.get("elapsed_s") or (tele["samples"]["t"][-1] if tele["samples"]["t"] else 0)
    if not seconds:
        raise UploadRejected("FIT_UNREADABLE", "讀不到這個 .fit 檔的跑步時間")
    minutes = Decimal(str(round(float(seconds) / 60, 2)))
    meters = session.get("distance_m") or (tele["samples"]["d"][-1] if tele["samples"]["d"] else None)
    km = round(float(meters) / 1000, 2) if meters else None
    on = at.astimezone(ZoneInfo(tz_name)).date()
    digest = hashlib.sha256(data).hexdigest()

    lock_athlete_training_load(tx, athlete_id)
    activity_id = tx.execute(_INSERT_ACTIVITY, {
        "a": athlete_id, "cmid": uuid.uuid5(uuid.NAMESPACE_URL, f"fit-upload:{athlete_id}:{digest}"),
        "fp": f"fit-upload:{digest}", "minutes": minutes, "rpe": rpe, "at": at, "tz": tz_name, "d": on,
        "load": minutes * rpe, "km": km, "metrics": json.dumps(_device_metrics(session)),
    }).scalar_one()

    easy = _easy_speed(tx, athlete_id)
    detection = detect_workout(tele, easy)
    summary: dict[str, Any] = {"kind": detection["kind"], "signature": detection["signature"],
                               "confidence": detection["confidence"], "moving_median_speed": moving_median_speed(tele)}
    reps_m: list[int | None] = []
    if detection["segments"]:
        hr = resolve_hr_profile(manual_max_hr=None, manual_resting_hr=None, device=tele["hr_profile"],
                                history_peak_30s=None, birth_year=None, on_date=on)
        analysis = analyse_workout(tele, detection["segments"],
                                   session_type=_KIND_TO_SESSION.get(detection["kind"], "other"),
                                   target_pace_s_per_km=None, hr=hr, easy_speed=easy)
        summary.update(history_summary(analysis["summary"]))
        reps_m = [s.get("nominal_m") for s in detection["segments"] if s["role"] == "work"]
        tx.execute(text("UPDATE completed_activities SET structure = CAST(:s AS jsonb) WHERE id = :id"),
                   {"s": json.dumps(structure_from_detection(analysis, detection)), "id": activity_id})
    tx.execute(_INSERT_TELEMETRY, {
        "id": activity_id, "a": athlete_id, "sport": tele["sport"], "sub": tele["sub_sport"],
        "device": tele["device"], "hr": json.dumps(tele["hr_profile"]), "laps": json.dumps(tele["laps"]),
        "events": json.dumps(tele["timer_events"]), "steps": json.dumps(tele["workout_steps"]),
        "samples": json.dumps(tele["samples"]), "peak": peak_rolling_hr(tele["samples"]), "name": None,
        "det": json.dumps(detection), "summ": json.dumps(summary)})
    tx.execute(text("DELETE FROM athlete_rest_days WHERE athlete_id = :a AND date = :d"), {"a": athlete_id, "d": on})
    recompute_training_load(tx, athlete_id, on)

    role = _day_role(tx, athlete_id, activity_id, on, at, detection["kind"])
    assignment = None
    if role in ("main", "run"):
        assignment = match_assignment(tx, athlete_id, activity_id, on, detection, reps_m)
        link(tx, athlete_id, activity_id, on, assignment.id if assignment else None, "auto")
    session_type = _KIND_TO_SESSION.get(detection["kind"], "other")
    label = signature_label(detection.get("signature"), session_type) if detection.get("signature") else None
    pace = float(seconds) / (float(meters) / 1000) if meters else None
    notified = _announce(tx, athlete_id, activity_id, on, role, km, pace, label, assignment)
    return {"activity_id": str(activity_id), "local_date": on.isoformat(), "day_role": role,
            "distance_km": km, "duration_minutes": float(minutes), "signature_label": label,
            "assignment": None if assignment is None else {
                "id": str(assignment.id), "title": assignment.title, "date": assignment.local_date.isoformat()},
            "notified_teams": notified}

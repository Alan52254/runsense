"""Real lap data and the AI workout analysis for one Completed Activity.

GET  /activities/{id}/telemetry                    real laps (+ detected role per lap)
GET  /activities/{id}/workout-analysis/detection   proposed segmentation to confirm
POST /activities/{id}/workout-analysis/preview     per-segment numbers for an edited segmentation
POST /activities/{id}/workout-analysis             analyse a confirmed segmentation (saved)
GET  /activities/{id}/workout-analysis             the saved analysis
GET  /activities/{id}/prescription                 what was prescribed (課表要求), with its source
POST /activities/{id}/prescription/parse           free text -> structured prescription (not saved)
PUT  /activities/{id}/prescription                 save the athlete's own prescription
DELETE /activities/{id}/prescription               drop it (back to coach / name / inferred)

The athlete always confirms (or corrects) the segmentation before anything
is analysed: which stretches were reps and which were recoveries is the
one judgement the whole analysis rests on, so it is never silently assumed.
"""

from __future__ import annotations

import json
import statistics
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app import workout_prescription
from app.db import actor_transaction, get_connection
from app.errors import InvalidWorkoutSegmentsError, TelemetryNotFoundError, WorkoutAnalysisNotFoundError
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.workout_analysis import HrProfile, analyse_workout, resolve_hr_profile, segment_stats
from app.workout_narrative import build_facts, signature_label, write_narrative
from app.workout_segmentation import SEGMENT_ROLES, build_grid, detect_workout, lap_bounds, signature

router = APIRouter()

SessionType = Literal["intervals", "tempo", "easy", "long", "race", "other"]
_KIND_TO_SESSION = {"intervals": "intervals", "tempo": "tempo", "continuous": "easy"}


# ---------------------------------------------------------------- schemas


class Segment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["warmup", "work", "rest", "set_rest", "strides", "cooldown", "steady"]
    start_s: int = Field(ge=0)
    end_s: int = Field(gt=0)
    nominal_m: int | None = Field(default=None, gt=0, le=50000)
    nominal_s: int | None = Field(default=None, gt=0, le=7200)
    interruptions: list[list[int]] | None = None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[Segment] = Field(min_length=1, max_length=200)


class PrescriptionBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reps: int = Field(ge=1, le=60)
    distance_m: int | None = Field(default=None, ge=50, le=42195)
    duration_s: int | None = Field(default=None, ge=5, le=7200)
    targets_s_per_km: list[float] = Field(default_factory=list, max_length=60)
    rest_s: int | None = Field(default=None, ge=0, le=3600)
    rest_after_s: int | None = Field(default=None, ge=0, le=7200)


class PrescriptionSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_text: str | None = Field(default=None, max_length=500)
    blocks: list[PrescriptionBlock] = Field(min_length=1, max_length=30)


class PrescriptionParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)


class AnalyseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[Segment] = Field(min_length=1, max_length=200)
    session_type: SessionType
    # optional target pace for the work segments, seconds per km
    target_pace_s_per_km: float | None = Field(default=None, ge=120, le=900)


# ---------------------------------------------------------------- data access

_SELECT_TELEMETRY = text(
    """
    SELECT t.activity_id, t.athlete_id, t.source, t.sport, t.sub_sport, t.device, t.hr_profile, t.laps,
           t.timer_events, t.workout_steps, t.samples, t.hr_peak_30s, t.auto_detection, t.auto_summary,
           t.activity_name, a.local_training_date, a.performed_at, a.duration_minutes, a.timezone_snapshot
      FROM activity_telemetry t
      JOIN completed_activities a ON a.id = t.activity_id
     WHERE t.activity_id = :activity_id AND t.athlete_id = :athlete_id AND a.deleted_at IS NULL
    """
)

_SELECT_PROFILE = text(
    "SELECT max_hr_bpm, resting_hr_bpm, birth_year FROM athlete_profiles WHERE user_id = :athlete_id"
)

_SELECT_ANALYSIS = text(
    """
    SELECT activity_id, session_type, segments, signature, target_pace_s_per_km, metrics, narrative,
           narrative_source, narrative_model, fallback_reason, updated_at
      FROM workout_analyses WHERE activity_id = :activity_id AND athlete_id = :athlete_id
    """
)

_UPSERT_ANALYSIS = text(
    """
    INSERT INTO workout_analyses (
        activity_id, athlete_id, session_type, segments, signature, target_pace_s_per_km, metrics,
        narrative, narrative_source, narrative_model, fallback_reason
    ) VALUES (
        :activity_id, :athlete_id, :session_type, CAST(:segments AS jsonb), :signature, :target,
        CAST(:metrics AS jsonb), :narrative, :narrative_source, :narrative_model, :fallback_reason
    )
    ON CONFLICT (activity_id) DO UPDATE SET
        session_type = EXCLUDED.session_type, segments = EXCLUDED.segments, signature = EXCLUDED.signature,
        target_pace_s_per_km = EXCLUDED.target_pace_s_per_km, metrics = EXCLUDED.metrics,
        narrative = EXCLUDED.narrative, narrative_source = EXCLUDED.narrative_source,
        narrative_model = EXCLUDED.narrative_model, fallback_reason = EXCLUDED.fallback_reason,
        updated_at = now()
    RETURNING updated_at
    """
)


def _load_telemetry(tx: Connection, activity_id: uuid.UUID, athlete_id: uuid.UUID) -> Any:
    row = tx.execute(_SELECT_TELEMETRY, {"activity_id": activity_id, "athlete_id": athlete_id}).first()
    if row is None:
        raise TelemetryNotFoundError()
    return row


def _tele_dict(row: Any) -> dict[str, Any]:
    return {"sport": row.sport, "sub_sport": row.sub_sport, "hr_profile": row.hr_profile, "laps": row.laps,
            "timer_events": row.timer_events, "workout_steps": row.workout_steps, "samples": row.samples}


def _easy_speed(tx: Connection, athlete_id: uuid.UUID, on: date) -> float | None:
    """The athlete's easy pace: median moving speed of their continuous runs
    in the year before this activity."""
    rows = tx.execute(
        text(
            """
            SELECT (t.auto_summary->>'moving_median_speed')::float AS s
              FROM activity_telemetry t JOIN completed_activities a ON a.id = t.activity_id
             WHERE t.athlete_id = :a AND a.deleted_at IS NULL AND t.auto_summary->>'kind' = 'continuous'
               AND a.local_training_date BETWEEN :lo AND :hi
            """
        ),
        {"a": athlete_id, "lo": on - timedelta(days=365), "hi": on},
    ).scalars().all()
    speeds = [s for s in rows if s]
    return statistics.median(speeds) if len(speeds) >= 5 else None


def _history_peak(tx: Connection, athlete_id: uuid.UUID, on: date) -> int | None:
    """Second-highest 30 s peak heart rate of the past year: one sensor
    artefact can produce a single impossible peak, two separate sessions
    agreeing is a real ceiling."""
    peaks = tx.execute(
        text(
            """
            SELECT t.hr_peak_30s FROM activity_telemetry t JOIN completed_activities a ON a.id = t.activity_id
             WHERE t.athlete_id = :a AND a.deleted_at IS NULL AND t.hr_peak_30s IS NOT NULL
               AND a.local_training_date BETWEEN :lo AND :hi
             ORDER BY t.hr_peak_30s DESC LIMIT 2
            """
        ),
        {"a": athlete_id, "lo": on - timedelta(days=365), "hi": on},
    ).scalars().all()
    return peaks[1] if len(peaks) == 2 else None


def _hr_profile(tx: Connection, athlete_id: uuid.UUID, tele_row: Any) -> tuple[HrProfile, dict]:
    prof = tx.execute(_SELECT_PROFILE, {"athlete_id": athlete_id}).first()
    on = tele_row.local_training_date
    hr = resolve_hr_profile(
        manual_max_hr=prof.max_hr_bpm if prof else None,
        manual_resting_hr=prof.resting_hr_bpm if prof else None,
        device=tele_row.hr_profile,
        history_peak_30s=_history_peak(tx, athlete_id, on),
        birth_year=prof.birth_year if prof else None,
        on_date=on,
    )
    manual = {"max_hr_bpm": prof.max_hr_bpm if prof else None,
              "resting_hr_bpm": prof.resting_hr_bpm if prof else None,
              "birth_year": prof.birth_year if prof else None}
    return hr, manual


def _same_session_history(tx: Connection, athlete_id: uuid.UUID, activity_id: uuid.UUID, sig: str | None,
                          on: date) -> list[dict]:
    """Earlier sessions of the same structure, newest first: an athlete's
    own confirmed analyses first, otherwise the import-time detection."""
    if not sig or sig == "continuous":
        return []
    rows = tx.execute(
        text(
            """
            SELECT a.local_training_date AS d,
                   COALESCE(w.signature, t.auto_summary->>'signature') AS sig,
                   COALESCE((w.metrics->'summary'->>'mean_work_pace_s_per_km')::float,
                            (t.auto_summary->>'mean_pace_s_per_km')::float) AS pace,
                   COALESCE((w.metrics->'summary'->>'mean_rep_hr')::float,
                            (t.auto_summary->>'mean_rep_hr')::float) AS hr
              FROM activity_telemetry t
              JOIN completed_activities a ON a.id = t.activity_id
              LEFT JOIN workout_analyses w ON w.activity_id = t.activity_id
             WHERE t.athlete_id = :a AND a.deleted_at IS NULL AND t.activity_id <> :id
               AND a.local_training_date < :on AND a.local_training_date >= :lo
               AND COALESCE(w.signature, t.auto_summary->>'signature') = :sig
             ORDER BY a.local_training_date DESC LIMIT 3
            """
        ),
        {"a": athlete_id, "id": activity_id, "on": on, "lo": on - timedelta(days=365), "sig": sig},
    ).all()
    return [{"date": r.d.isoformat(), "signature": r.sig, "mean_pace_s_per_km": r.pace,
             "mean_rep_hr": round(r.hr) if r.hr else None} for r in rows if r.pace]


def _validate_segments(segments: list[Segment], n: int, session_type: str) -> list[dict]:
    segs = sorted((s.model_dump(exclude_none=True) for s in segments), key=lambda s: s["start_s"])
    prev_end = 0
    for s in segs:
        if s["role"] not in SEGMENT_ROLES:
            raise InvalidWorkoutSegmentsError(f"未知的分段類型 {s['role']}")
        if s["end_s"] <= s["start_s"]:
            raise InvalidWorkoutSegmentsError("分段的結束時間必須晚於開始時間")
        if s["start_s"] < prev_end:
            raise InvalidWorkoutSegmentsError("分段時間重疊")
        if s["end_s"] > n + 1:
            raise InvalidWorkoutSegmentsError("分段超出這筆紀錄的時間範圍")
        prev_end = s["end_s"]
        if s["role"] != "work":
            s.pop("nominal_m", None)
            s.pop("nominal_s", None)
        for a, b in s.get("interruptions", []) or []:
            if not (s["start_s"] <= a < b <= s["end_s"]):
                raise InvalidWorkoutSegmentsError("中途停下的時間不在該趟範圍內")
    if session_type in ("intervals",) and not any(s["role"] == "work" for s in segs):
        raise InvalidWorkoutSegmentsError("間歇課表至少要有一段「強度」")
    return segs


def _lap_rows(tele: dict, segments: list[dict]) -> list[dict[str, Any]]:
    """The watch's own laps, each labelled with the segment role it falls
    in (by majority overlap) -- History's lap table."""
    out = []
    for k, (lap, start, end) in enumerate(lap_bounds(tele), 1):
        dist = lap.get("distance_m")
        timer = lap.get("timer_s")
        if (dist is None or dist < 1) and (timer or 0) < 1:
            continue
        overlap: dict[str, float] = {}
        for s in segments:
            ov = min(end, s["end_s"]) - max(start, s["start_s"])
            if ov > 0:
                overlap[s["role"]] = overlap.get(s["role"], 0) + ov
        out.append({
            "lap_number": k,
            "start_s": round(start),
            "end_s": round(end),
            "distance_m": round(dist, 1) if dist is not None else None,
            "timer_s": round(timer, 1) if timer is not None else None,
            "pace_s_per_km": round(timer / (dist / 1000), 1) if dist and dist > 20 and timer else None,
            "avg_hr": lap.get("avg_hr"),
            "max_hr": lap.get("max_hr"),
            "avg_cadence": lap.get("avg_cadence"),
            "trigger": lap.get("trigger"),
            "role": max(overlap, key=overlap.get) if overlap else None,
        })
    return out


def _current_reps(tele: dict, segments: list[dict]) -> tuple[list[dict], list[dict]]:
    g = build_grid(tele["samples"], tele["timer_events"])
    stats = [segment_stats(g, s, i) for i, s in enumerate(segments)]
    reps = [x for x in stats if x["role"] == "work"]
    for k, r in enumerate(reps, 1):
        r["rep_number"] = k
    return reps, [x for x in stats if x["role"] in ("rest", "set_rest")]


def _stored_or_coach_prescription(tx: Connection, athlete_id: uuid.UUID, activity_id: uuid.UUID,
                                  on: date) -> dict | None:
    """Priority: what the athlete typed > the coach's assignment for that
    date > the workout written into the activity name. (An inferred one
    is the caller's fallback.)"""
    rows = {r.source: r for r in tx.execute(
        text("SELECT source, raw_text, prescription FROM workout_prescriptions "
             "WHERE activity_id = :id AND athlete_id = :a"), {"id": activity_id, "a": athlete_id}).all()}
    if "athlete_text" in rows:
        return rows["athlete_text"].prescription
    assignment = tx.execute(
        text("SELECT title, structure FROM assigned_workouts WHERE athlete_id = :a AND local_date = :d "
             "ORDER BY created_at DESC LIMIT 1"), {"a": athlete_id, "d": on}).first()
    if assignment is not None:
        p = workout_prescription.from_assignment(assignment.structure or [], assignment.title)
        if p is None:
            # the coach prescribed an easy day: strides or pick-ups inside it
            # are not an interval session to be reconstructed and graded
            return {"source": "coach_assignment", "easy_day": True, "title": assignment.title, "blocks": []}
        if _is_main_session(tx, athlete_id, activity_id, on):
            return p
    if "activity_name" in rows:
        return rows["activity_name"].prescription
    return None


def _is_main_session(tx: Connection, athlete_id: uuid.UUID, activity_id: uuid.UUID, on: date) -> bool:
    """A day's assigned workout belongs to that day's main session -- the
    longest run that reads as a workout -- not to the warm-up, the cool-down
    or a few strides recorded as separate activities around it."""
    main = tx.execute(
        text(
            """
            SELECT a.id FROM completed_activities a JOIN activity_telemetry t ON t.activity_id = a.id
             WHERE a.athlete_id = :a AND a.local_training_date = :d AND a.deleted_at IS NULL
               AND t.auto_summary->>'kind' IN ('intervals', 'tempo')
             ORDER BY a.distance_km DESC NULLS LAST LIMIT 1
            """
        ),
        {"a": athlete_id, "d": on},
    ).scalar_one_or_none()
    return main is None or main == activity_id


def _prescription_view(prescription: dict | None, reps: list[dict], rests: list[dict], kind: str) -> dict | None:
    """The prescription to show and analyse with: the real one when there
    is one (missing targets filled from the run and marked so), otherwise
    the inferred one -- always with its source and whether it can grade."""
    if not reps or (prescription or {}).get("easy_day"):
        return None
    inferred = workout_prescription.infer(reps, rests, kind)
    p = prescription
    if p is None:
        p = inferred
    elif inferred:
        p = workout_prescription.fill_missing_targets(json.loads(json.dumps(p)), inferred)
    if p is None:
        return None
    alignment = workout_prescription.align(p, reps)
    source = p.get("source", "inferred")
    return {
        **p,
        "title": p.get("title") or workout_prescription.describe(p),
        "source_label": workout_prescription.SOURCE_LABEL.get(source, source),
        "gradable": source in workout_prescription.GRADABLE_SOURCES and not alignment["blocking"],
        "issues": alignment["issues"],
        "per_rep": alignment["per_rep"],
    }


_LINK_WINDOW = timedelta(hours=2)


def _linked_records(tx: Connection, athlete_id: uuid.UUID, row: Any) -> dict:
    """Separately recorded warm-up / cool-down: the athlete's other easy
    runs ending within 2 hours before this session starts, or starting
    within 2 hours after it ends."""
    start = row.performed_at
    end = start + timedelta(minutes=float(row.duration_minutes))
    candidates = tx.execute(
        text(
            """
            SELECT a.id, a.performed_at, a.duration_minutes, a.distance_km, a.timezone_snapshot,
                   (a.device_metrics->>'avgHeartRate')::int AS avg_hr, t.auto_summary->>'kind' AS kind
              FROM completed_activities a LEFT JOIN activity_telemetry t ON t.activity_id = a.id
             WHERE a.athlete_id = :a AND a.deleted_at IS NULL AND a.id <> :id
               AND a.performed_at BETWEEN :lo AND :hi
            """
        ),
        {"a": athlete_id, "id": row.activity_id, "lo": start - timedelta(hours=4), "hi": end + _LINK_WINDOW},
    ).all()
    out: dict = {}
    for c in candidates:
        if c.kind in ("intervals", "tempo") or (c.distance_km and float(c.distance_km) > 8):
            continue
        c_end = c.performed_at + timedelta(minutes=float(c.duration_minutes))
        tz = ZoneInfo(c.timezone_snapshot or "Asia/Taipei")
        rec = {
            "activity_id": str(c.id),
            "start_local": c.performed_at.astimezone(tz).strftime("%H:%M"),
            "duration_s": round(float(c.duration_minutes) * 60),
            "distance_km": float(c.distance_km or 0),
            "avg_hr": c.avg_hr,
        }
        if c_end <= start + timedelta(minutes=2) and start - c_end <= _LINK_WINDOW:
            if "warmup" not in out or c.performed_at > datetime.fromisoformat(out["warmup"]["_start"]):
                out["warmup"] = {**rec, "_start": c.performed_at.isoformat()}
        elif c.performed_at >= end - timedelta(minutes=2) and c.performed_at - end <= _LINK_WINDOW:
            if "cooldown" not in out or c.performed_at < datetime.fromisoformat(out["cooldown"]["_start"]):
                out["cooldown"] = {**rec, "_start": c.performed_at.isoformat()}
    for v in out.values():
        v.pop("_start", None)
    return out


def _analysis_kind(segments: list[dict], session_type: str) -> str:
    return "tempo" if session_type == "tempo" else "intervals"


# ---------------------------------------------------------------- routes


@router.get("/activities/{activity_id}/telemetry")
def get_telemetry(
    activity_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        athlete_id = uuid.UUID(actor)
        row = _load_telemetry(tx, activity_id, athlete_id)
        saved = tx.execute(_SELECT_ANALYSIS, {"activity_id": activity_id, "athlete_id": athlete_id}).first()
        stored = _stored_or_coach_prescription(tx, athlete_id, activity_id, row.local_training_date)
        linked = _linked_records(tx, athlete_id, row)
    tele = _tele_dict(row)
    detection = row.auto_detection or detect_workout(tele)
    segments = saved.segments if saved else detection["segments"]
    reps, rests = _current_reps(tele, segments)
    kind = (saved.session_type if saved else _KIND_TO_SESSION.get(detection["kind"], "other"))
    view = _prescription_view(stored, reps, rests, _analysis_kind(segments, kind)) \
        if detection["kind"] in ("intervals", "tempo") or saved else None
    return {
        "activity_name": row.activity_name,
        "source": row.source,
        "prescription": view,
        "coach_easy_day": (stored or {}).get("title") if (stored or {}).get("easy_day") else None,
        "linked": linked,
        "activity_id": str(activity_id),
        "sport": row.sport,
        "sub_sport": row.sub_sport,
        "device": row.device,
        "laps": _lap_rows(tele, segments),
        "detection": {"kind": detection["kind"], "signature": detection["signature"],
                      "confidence": detection["confidence"]},
        "has_analysis": saved is not None,
        "roles_from": "analysis" if saved else "detection",
    }


@router.get("/activities/{activity_id}/workout-analysis/detection")
def get_detection(
    activity_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        athlete_id = uuid.UUID(actor)
        row = _load_telemetry(tx, activity_id, athlete_id)
        easy = _easy_speed(tx, athlete_id, row.local_training_date)
        hr, manual = _hr_profile(tx, athlete_id, row)
        saved = tx.execute(_SELECT_ANALYSIS, {"activity_id": activity_id, "athlete_id": athlete_id}).first()
        stored = _stored_or_coach_prescription(tx, athlete_id, activity_id, row.local_training_date)
        linked = _linked_records(tx, athlete_id, row)
    tele = _tele_dict(row)
    detection = detect_workout(tele, easy)
    g = build_grid(tele["samples"], tele["timer_events"])
    reps, rests = _current_reps(tele, detection["segments"])
    suggested = "easy" if (stored or {}).get("easy_day") else _KIND_TO_SESSION.get(detection["kind"], "other")
    return {
        "activity_name": row.activity_name,
        "prescription": _prescription_view(stored, reps, rests, _analysis_kind(detection["segments"], suggested)),
        "has_real_prescription": stored is not None and not stored.get("easy_day"),
        "linked": linked,
        "activity_id": str(activity_id),
        "detection": detection,
        "suggested_session_type": _KIND_TO_SESSION.get(detection["kind"], "other"),
        "segments_preview": [segment_stats(g, s, i) for i, s in enumerate(detection["segments"])],
        "duration_s": g.n,
        "sub_sport": row.sub_sport,
        "laps": _lap_rows(tele, detection["segments"]),
        "hr_profile": hr.as_dict(),
        "hr_manual": manual,
        "easy_pace_s_per_km": round(1000 / easy, 1) if easy else None,
        "saved_analysis": _analysis_payload(saved) if saved else None,
    }


@router.post("/activities/{activity_id}/workout-analysis/preview")
def preview_segments(
    activity_id: uuid.UUID,
    payload: PreviewRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        row = _load_telemetry(tx, activity_id, uuid.UUID(actor))
    tele = _tele_dict(row)
    g = build_grid(tele["samples"], tele["timer_events"])
    segs = _validate_segments(payload.segments, g.n, "other")
    return {"segments_preview": [segment_stats(g, s, i) for i, s in enumerate(segs)],
            "signature": signature(segs, "intervals" if any(s["role"] == "work" for s in segs) else "continuous", g)}


@router.post("/activities/{activity_id}/workout-analysis")
def analyse(
    activity_id: uuid.UUID,
    payload: AnalyseRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    athlete_id = uuid.UUID(actor)
    with actor_transaction(conn, actor) as tx:
        row = _load_telemetry(tx, activity_id, athlete_id)
        tele = _tele_dict(row)
        g = build_grid(tele["samples"], tele["timer_events"])
        segs = _validate_segments(payload.segments, g.n, payload.session_type)
        works = [s for s in segs if s["role"] == "work"]
        kind = ("intervals" if len(works) >= 2 else "tempo" if works and payload.session_type == "tempo"
                else "intervals" if works else "continuous")
        sig = signature(segs, kind, g)
        easy = _easy_speed(tx, athlete_id, row.local_training_date)
        hr, _manual = _hr_profile(tx, athlete_id, row)
        history = _same_session_history(tx, athlete_id, activity_id, sig, row.local_training_date)
        stored = _stored_or_coach_prescription(tx, athlete_id, activity_id, row.local_training_date)
        linked = _linked_records(tx, athlete_id, row)
    # the analysis and the language-model call run outside the transaction
    analysis = analyse_workout(tele, segs, session_type=payload.session_type,
                               target_pace_s_per_km=payload.target_pace_s_per_km, hr=hr,
                               easy_speed=easy, history=history,
                               prescription=None if (stored or {}).get("easy_day") else stored, linked=linked)
    facts = build_facts(signature_label=signature_label(sig, payload.session_type),
                        session_type=payload.session_type,
                        activity_date=row.local_training_date.isoformat(), analysis=analysis,
                        sub_sport=row.sub_sport)
    narrative = write_narrative(facts, rep_count=len(analysis["reps"]))
    metrics = {"segment_stats": analysis["segments"], "summary": analysis["summary"],
               "findings": analysis["findings"], "data_notes": analysis["data_notes"]}
    with actor_transaction(conn, actor) as tx:
        updated_at = tx.execute(_UPSERT_ANALYSIS, {
            "activity_id": activity_id, "athlete_id": athlete_id, "session_type": payload.session_type,
            "segments": json.dumps(segs), "signature": sig, "target": payload.target_pace_s_per_km,
            "metrics": json.dumps(metrics), "narrative": narrative["text"],
            "narrative_source": narrative["source"], "narrative_model": narrative["model"],
            "fallback_reason": narrative["fallback_reason"],
        }).scalar_one()
    return {
        "activity_id": str(activity_id),
        "session_type": payload.session_type,
        "segments": segs,
        "signature": sig,
        "signature_label": signature_label(sig, payload.session_type),
        "target_pace_s_per_km": payload.target_pace_s_per_km,
        **metrics,
        "narrative": narrative["text"],
        "narrative_source": narrative["source"],
        "narrative_model": narrative["model"],
        "fallback_reason": narrative["fallback_reason"],
        "updated_at": updated_at.isoformat(),
    }


@router.get("/activities/{activity_id}/workout-analysis")
def get_analysis(
    activity_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        saved = tx.execute(_SELECT_ANALYSIS, {"activity_id": activity_id, "athlete_id": uuid.UUID(actor)}).first()
    if saved is None:
        raise WorkoutAnalysisNotFoundError()
    return _analysis_payload(saved)


def _analysis_payload(saved: Any) -> dict[str, Any]:
    return {
        "activity_id": str(saved.activity_id),
        "session_type": saved.session_type,
        "segments": saved.segments,
        "signature": saved.signature,
        "signature_label": signature_label(saved.signature, saved.session_type),
        "target_pace_s_per_km": float(saved.target_pace_s_per_km) if saved.target_pace_s_per_km else None,
        **saved.metrics,
        "narrative": saved.narrative,
        "narrative_source": saved.narrative_source,
        "narrative_model": saved.narrative_model,
        "fallback_reason": saved.fallback_reason,
        "updated_at": saved.updated_at.isoformat(),
    }


@router.get("/activities/{activity_id}/prescription")
def get_prescription(
    activity_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        athlete_id = uuid.UUID(actor)
        row = _load_telemetry(tx, activity_id, athlete_id)
        saved = tx.execute(_SELECT_ANALYSIS, {"activity_id": activity_id, "athlete_id": athlete_id}).first()
        stored = _stored_or_coach_prescription(tx, athlete_id, activity_id, row.local_training_date)
    tele = _tele_dict(row)
    detection = row.auto_detection or detect_workout(tele)
    segments = saved.segments if saved else detection["segments"]
    reps, rests = _current_reps(tele, segments)
    return {"activity_name": row.activity_name,
            "prescription": _prescription_view(stored, reps, rests, "intervals"),
            "has_real_prescription": stored is not None and not stored.get("easy_day")}


@router.post("/activities/{activity_id}/prescription/parse")
def parse_prescription(
    activity_id: uuid.UUID,
    payload: PrescriptionParseRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        athlete_id = uuid.UUID(actor)
        row = _load_telemetry(tx, activity_id, athlete_id)
        saved = tx.execute(_SELECT_ANALYSIS, {"activity_id": activity_id, "athlete_id": athlete_id}).first()
    tele = _tele_dict(row)
    detection = row.auto_detection or detect_workout(tele)
    segments = saved.segments if saved else detection["segments"]
    reps, _rests = _current_reps(tele, segments)
    result = workout_prescription.parse_text(payload.text)
    p = result["prescription"]
    issues = workout_prescription.align(p, reps)["issues"] if p else []
    return {"prescription": p, "problems": result["problems"], "alignment_issues": issues,
            "title": p["title"] if p else None}


@router.put("/activities/{activity_id}/prescription")
def save_prescription(
    activity_id: uuid.UUID,
    payload: PrescriptionSaveRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    prescription = {"source": "athlete_text", "raw_text": payload.raw_text,
                    "blocks": [b.model_dump() for b in payload.blocks]}
    for b in prescription["blocks"]:
        if b["distance_m"] is None and b["duration_s"] is None:
            raise InvalidWorkoutSegmentsError("每一組都要有距離或時間")
        if b["targets_s_per_km"] and len(b["targets_s_per_km"]) not in (1, b["reps"]):
            raise InvalidWorkoutSegmentsError("目標配速數量要等於趟數，或只填一個共用")
        if any(not 120 <= t <= 900 for t in b["targets_s_per_km"]):
            raise InvalidWorkoutSegmentsError("目標配速不合理")
    prescription["title"] = workout_prescription.describe(prescription)
    with actor_transaction(conn, actor) as tx:
        athlete_id = uuid.UUID(actor)
        _load_telemetry(tx, activity_id, athlete_id)
        tx.execute(
            text(
                """
                INSERT INTO workout_prescriptions (activity_id, athlete_id, source, raw_text, prescription)
                VALUES (:id, :a, 'athlete_text', :raw, CAST(:p AS jsonb))
                ON CONFLICT (activity_id) DO UPDATE SET source = 'athlete_text', raw_text = EXCLUDED.raw_text,
                    prescription = EXCLUDED.prescription, updated_at = now()
                """
            ),
            {"id": activity_id, "a": athlete_id, "raw": payload.raw_text, "p": json.dumps(prescription)},
        )
    return {"prescription": prescription}


@router.delete("/activities/{activity_id}/prescription", status_code=204)
def delete_prescription(
    activity_id: uuid.UUID,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> None:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        tx.execute(text("DELETE FROM workout_prescriptions WHERE activity_id = :id AND athlete_id = :a "
                        "AND source = 'athlete_text'"), {"id": activity_id, "a": uuid.UUID(actor)})

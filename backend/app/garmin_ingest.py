"""Garmin wellness telemetry and runtime .fit activity ingestion (ADR-0004).

Handles:
1. Forced-RLS `athlete_wellness_daily` queries (`get_latest_wellness`,
   `get_wellness_trend`) with 28-day baseline resting-HR delta calculation.
2. Deterministic Banister HR-TRIMP RPE fallback (`compute_hr_trimp_rpe`) so
   wrist-band runs lacking manual RPE keep AU load continuity without violating
   `CHECK (rpe BETWEEN 1 AND 10)`.
3. Runtime `.fit` parsing via `app.fit_telemetry.parse_fit()` while strictly
   stripping GPS coordinates before writing `completed_activities` and
   `activity_telemetry`.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, Mapping, Sequence
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.fit_telemetry import FitParseError, parse_fit, peak_rolling_hr
from app.training_load_store import lock_athlete_training_load, recompute_training_load

_DISALLOWED_PII_KEYS = frozenset(
    {
        "email",
        "phone",
        "address",
        "lat",
        "lon",
        "lng",
        "latitude",
        "longitude",
        "position_lat",
        "position_long",
        "gps",
        "route_points",
    }
)


@dataclass(frozen=True)
class WellnessSummary:
    local_date: date
    resting_hr_bpm: int | None = None
    resting_hr_delta: float | None = None
    hrv_ms: float | None = None
    hrv_status: str | None = None
    sleep_hours: float | None = None
    sleep_score: int | None = None
    body_battery_high: int | None = None
    body_battery_low: int | None = None
    body_battery_recent: int | None = None
    stress_avg: int | None = None
    vo2max: float | None = None
    race_pred_5k_s: int | None = None
    source: str = "garmin_gdpr"

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_date": self.local_date.isoformat(),
            "resting_hr_bpm": self.resting_hr_bpm,
            "resting_hr_delta": self.resting_hr_delta,
            "hrv_ms": self.hrv_ms,
            "hrv_status": self.hrv_status,
            "sleep_hours": self.sleep_hours,
            "sleep_score": self.sleep_score,
            "body_battery_high": self.body_battery_high,
            "body_battery_low": self.body_battery_low,
            "body_battery_recent": self.body_battery_recent,
            "stress_avg": self.stress_avg,
            "vo2max": self.vo2max,
            "race_pred_5k_s": self.race_pred_5k_s,
            "source": self.source,
        }


def compute_hr_trimp_rpe(
    duration_minutes: float,
    avg_hr: float | None,
    max_hr: float | None = None,
    rest_hr: float | None = None,
    sex: str = "male",
) -> tuple[int, float, str]:
    """Compute deterministic Banister HR-TRIMP RPE fallback (1..10) and AU load.

    Preserves `completed_activities.rpe BETWEEN 1 AND 10` and `unit = 'AU'`,
    recording `HR_TRIMP` when heart-rate telemetry is available or
    `DURATION_DEFAULT` when heart rate is missing.
    """
    dur = max(1.0, float(duration_minutes or 0.0))
    if avg_hr is None or avg_hr <= 0:
        rpe = 4
        return rpe, round(dur * rpe, 2), "DURATION_DEFAULT"

    eff_max = float(max_hr) if max_hr is not None and max_hr > 100 else 190.0
    eff_rest = (
        float(rest_hr) if rest_hr is not None and 30 <= rest_hr < eff_max else 55.0
    )
    hrr_span = max(1.0, eff_max - eff_rest)
    delta_hrr = max(0.0, min(1.2, (float(avg_hr) - eff_rest) / hrr_span))
    b_coeff = 1.67 if str(sex or "").lower() == "female" else 1.92
    # Banister TRIMP per-minute intensity factor anchors the physiological curve.
    trimp_rate = delta_hrr * 0.64 * math.exp(b_coeff * delta_hrr)
    # Normalise ~[0, 3.0] TRIMP/min & HRR reserve cleanly into integer RPE [1, 10].
    blended = 0.55 * min(1.0, delta_hrr / 0.92) + 0.45 * min(1.0, trimp_rate / 2.6)
    clamped_rpe = max(1, min(10, round(1 + 9 * blended)))
    return clamped_rpe, round(dur * float(clamped_rpe), 2), "HR_TRIMP"


def _summary_from_row(row: Any, baseline_rhr: float | None) -> WellnessSummary:
    rhr = int(row.resting_hr_bpm) if row.resting_hr_bpm is not None else None
    delta = (
        round(float(rhr) - float(baseline_rhr), 2)
        if rhr is not None and baseline_rhr is not None
        else None
    )
    return WellnessSummary(
        local_date=row.local_date,
        resting_hr_bpm=rhr,
        resting_hr_delta=delta,
        hrv_ms=float(row.hrv_ms) if row.hrv_ms is not None else None,
        hrv_status=row.hrv_status,
        sleep_hours=float(row.sleep_hours) if row.sleep_hours is not None else None,
        sleep_score=int(row.sleep_score) if row.sleep_score is not None else None,
        body_battery_high=int(row.body_battery_high) if row.body_battery_high is not None else None,
        body_battery_low=int(row.body_battery_low) if row.body_battery_low is not None else None,
        body_battery_recent=int(row.body_battery_recent) if row.body_battery_recent is not None else None,
        stress_avg=int(row.stress_avg) if row.stress_avg is not None else None,
        vo2max=float(row.vo2max) if row.vo2max is not None else None,
        race_pred_5k_s=int(row.race_pred_5k_s) if row.race_pred_5k_s is not None else None,
        source=str(row.source or "garmin_gdpr"),
    )


def _baseline_rhr(
    conn: Connection, athlete_id: uuid.UUID, before_date: date
) -> float | None:
    val = conn.execute(
        text(
            "SELECT AVG(resting_hr_bpm)::float FROM athlete_wellness_daily "
            "WHERE athlete_id = :a AND local_date >= :lo AND local_date < :hi "
            "AND resting_hr_bpm IS NOT NULL"
        ),
        {
            "a": athlete_id,
            "lo": before_date - timedelta(days=28),
            "hi": before_date,
        },
    ).scalar_one_or_none()
    return float(val) if val is not None else None


def get_latest_wellness(
    conn: Connection,
    athlete_id: uuid.UUID,
    on_date: date | None = None,
) -> WellnessSummary | None:
    """Return latest daily wellness row on or before `on_date`, plus RHR delta."""
    try:
        cm = conn.begin_nested() if hasattr(conn, "begin_nested") else nullcontext()
        with cm:
            if on_date is not None:
                row = conn.execute(
                    text(
                        "SELECT local_date, resting_hr_bpm, hrv_ms, hrv_status, sleep_hours, "
                        "sleep_score, body_battery_high, body_battery_low, body_battery_recent, "
                        "stress_avg, vo2max, race_pred_5k_s, source "
                        "FROM athlete_wellness_daily "
                        "WHERE athlete_id = :a AND local_date <= :d "
                        "ORDER BY local_date DESC LIMIT 1"
                    ),
                    {"a": athlete_id, "d": on_date},
                ).first()
            else:
                row = conn.execute(
                    text(
                        "SELECT local_date, resting_hr_bpm, hrv_ms, hrv_status, sleep_hours, "
                        "sleep_score, body_battery_high, body_battery_low, body_battery_recent, "
                        "stress_avg, vo2max, race_pred_5k_s, source "
                        "FROM athlete_wellness_daily "
                        "WHERE athlete_id = :a ORDER BY local_date DESC LIMIT 1"
                    ),
                    {"a": athlete_id},
                ).first()
            if row is None:
                return None
            base = _baseline_rhr(conn, athlete_id, row.local_date)
            return _summary_from_row(row, base)
    except SQLAlchemyError:
        return None


def get_wellness_trend(
    conn: Connection,
    athlete_id: uuid.UUID,
    on_date: date | None = None,
    *,
    days: int = 14,
) -> list[WellnessSummary]:
    """Return chronological daily wellness summaries over the requested window."""
    span = max(1, min(90, int(days)))
    end_date = on_date or date.today()
    start_date = end_date - timedelta(days=span - 1)
    try:
        cm = conn.begin_nested() if hasattr(conn, "begin_nested") else nullcontext()
        with cm:
            rows = conn.execute(
                text(
                    "SELECT local_date, resting_hr_bpm, hrv_ms, hrv_status, sleep_hours, "
                    "sleep_score, body_battery_high, body_battery_low, body_battery_recent, "
                    "stress_avg, vo2max, race_pred_5k_s, source "
                    "FROM athlete_wellness_daily "
                    "WHERE athlete_id = :a AND local_date BETWEEN :lo AND :hi "
                    "ORDER BY local_date ASC"
                ),
                {"a": athlete_id, "lo": start_date, "hi": end_date},
            ).all()
            if not rows:
                return []
            base = _baseline_rhr(conn, athlete_id, rows[0].local_date)
            return [_summary_from_row(row, base) for row in rows]
    except SQLAlchemyError:
        return []


def _parse_date(raw: Any) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    text_val = str(raw or "").strip()[:10]
    return date.fromisoformat(text_val)


def _normalise_wellness_record(
    raw: Mapping[str, Any], *, default_source: str
) -> dict[str, Any]:
    for k in raw:
        if str(k).lower() in _DISALLOWED_PII_KEYS:
            raise ValueError(f"disallowed PII/location field: {k}")

    local_date = _parse_date(raw.get("local_date") or raw.get("calendarDate"))
    sleep_hours = raw.get("sleep_hours")
    if sleep_hours is None:
        deep = float(raw.get("deepSleepSeconds") or 0.0)
        light = float(raw.get("lightSleepSeconds") or 0.0)
        rem = float(raw.get("remSleepSeconds") or 0.0)
        total_sec = deep + light + rem
        if total_sec > 0:
            sleep_hours = round(total_sec / 3600.0, 2)

    bb_stat = raw.get("bodyBattery") or {}
    scores = raw.get("sleepScores") or {}
    sleep_score = raw.get("sleep_score")
    if sleep_score is None and isinstance(scores, Mapping):
        sleep_score = scores.get("overallScore")

    return {
        "local_date": local_date,
        "resting_hr_bpm": _opt_int(raw.get("resting_hr_bpm") or raw.get("restingHeartRate")),
        "hrv_ms": _opt_float(raw.get("hrv_ms") or raw.get("hrvMs")),
        "hrv_status": _opt_str(raw.get("hrv_status") or raw.get("hrvStatus")),
        "sleep_hours": _opt_float(sleep_hours),
        "sleep_score": _opt_int(sleep_score),
        "body_battery_high": _opt_int(
            raw.get("body_battery_high")
            or raw.get("bodyBatteryHighestValue")
            or (bb_stat.get("highest") if isinstance(bb_stat, Mapping) else None)
        ),
        "body_battery_low": _opt_int(
            raw.get("body_battery_low")
            or raw.get("bodyBatteryLowestValue")
            or (bb_stat.get("lowest") if isinstance(bb_stat, Mapping) else None)
        ),
        "body_battery_recent": _opt_int(
            raw.get("body_battery_recent")
            or raw.get("bodyBatteryMostRecentValue")
            or (bb_stat.get("recent") if isinstance(bb_stat, Mapping) else None)
        ),
        "stress_avg": _opt_int(raw.get("stress_avg") or raw.get("averageStressLevel")),
        "vo2max": _opt_float(raw.get("vo2max")),
        "race_pred_5k_s": _opt_int(raw.get("race_pred_5k_s")),
        "source": str(raw.get("source") or default_source)[:64],
    }


def _opt_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    return int(round(float(val)))


def _opt_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    v = float(val)
    return v if math.isfinite(v) else None


def _opt_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


_UPSERT_WELLNESS_SQL = text(
    """
    INSERT INTO athlete_wellness_daily (
        athlete_id, local_date, resting_hr_bpm, hrv_ms, hrv_status, sleep_hours,
        sleep_score, body_battery_high, body_battery_low, body_battery_recent,
        stress_avg, vo2max, race_pred_5k_s, source
    ) VALUES (
        :athlete_id, :local_date, :resting_hr_bpm, :hrv_ms, :hrv_status, :sleep_hours,
        :sleep_score, :body_battery_high, :body_battery_low, :body_battery_recent,
        :stress_avg, :vo2max, :race_pred_5k_s, :source
    )
    ON CONFLICT (athlete_id, local_date) DO UPDATE SET
        resting_hr_bpm = COALESCE(EXCLUDED.resting_hr_bpm, athlete_wellness_daily.resting_hr_bpm),
        hrv_ms = COALESCE(EXCLUDED.hrv_ms, athlete_wellness_daily.hrv_ms),
        hrv_status = COALESCE(EXCLUDED.hrv_status, athlete_wellness_daily.hrv_status),
        sleep_hours = COALESCE(EXCLUDED.sleep_hours, athlete_wellness_daily.sleep_hours),
        sleep_score = COALESCE(EXCLUDED.sleep_score, athlete_wellness_daily.sleep_score),
        body_battery_high = COALESCE(EXCLUDED.body_battery_high, athlete_wellness_daily.body_battery_high),
        body_battery_low = COALESCE(EXCLUDED.body_battery_low, athlete_wellness_daily.body_battery_low),
        body_battery_recent = COALESCE(EXCLUDED.body_battery_recent, athlete_wellness_daily.body_battery_recent),
        stress_avg = COALESCE(EXCLUDED.stress_avg, athlete_wellness_daily.stress_avg),
        vo2max = COALESCE(EXCLUDED.vo2max, athlete_wellness_daily.vo2max),
        race_pred_5k_s = COALESCE(EXCLUDED.race_pred_5k_s, athlete_wellness_daily.race_pred_5k_s),
        source = EXCLUDED.source,
        updated_at = now()
    """
)


def upsert_wellness_rows(
    conn: Connection,
    athlete_id: uuid.UUID,
    rows: Sequence[Mapping[str, Any]],
    *,
    source: str = "garmin_gdpr",
) -> int:
    """Persist normalised daily wellness rows for `athlete_id`."""
    count = 0
    for raw in rows:
        params = _normalise_wellness_record(raw, default_source=source)
        params["athlete_id"] = athlete_id
        conn.execute(_UPSERT_WELLNESS_SQL, params)
        count += 1
    return count


def ingest_fit_activity(
    conn: Connection,
    athlete_id: uuid.UUID,
    fit_bytes: bytes,
    *,
    rpe: int | None = None,
    timezone_name: str = "Asia/Taipei",
    sex: str = "male",
    client_mutation_id: str | None = None,
    activity_name: str | None = None,
) -> dict[str, Any]:
    """Parse binary `.fit` file, strip GPS, resolve HR-TRIMP RPE, and persist.

    Raises `FitParseError` on corrupt or incomplete `.fit` payloads.
    """
    tele = parse_fit(fit_bytes)
    session = tele.get("session") or {}
    start_time: datetime = tele["start_time"]
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(timezone_name)
    local_training_date = start_time.astimezone(tz).date()

    timer_s = session.get("timer_s") or session.get("elapsed_s")
    if timer_s is None:
        t_samples = (tele.get("samples") or {}).get("t") or []
        timer_s = float(t_samples[-1]) if t_samples else 60.0
    duration_minutes = max(1.0, round(float(timer_s) / 60.0, 2))
    distance_m = session.get("distance_m")
    distance_km = round(float(distance_m) / 1000.0, 3) if distance_m is not None else None

    avg_hr = session.get("avg_hr")
    max_hr = session.get("max_hr")
    hr_profile = dict(tele.get("hr_profile") or {})
    rest_hr = hr_profile.get("resting_hr")
    profile_max = hr_profile.get("max_hr") or max_hr

    if rpe is not None:
        resolved_rpe = max(1, min(10, int(rpe)))
        session_load = round(duration_minutes * float(resolved_rpe), 2)
        source_metric = "SESSION_RPE"
    else:
        workout_rpe = session.get("workout_rpe")
        if workout_rpe is not None and float(workout_rpe) > 0:
            raw_val = float(workout_rpe)
            scaled = round(raw_val / 10.0) if raw_val > 10 else round(raw_val)
            resolved_rpe = max(1, min(10, int(scaled)))
            session_load = round(duration_minutes * float(resolved_rpe), 2)
            source_metric = "SESSION_RPE"
        else:
            resolved_rpe, session_load, source_metric = compute_hr_trimp_rpe(
                duration_minutes, avg_hr, profile_max, rest_hr, sex=sex
            )

    device_metrics: dict[str, Any] = {}
    if avg_hr is not None:
        device_metrics["avgHeartRate"] = round(float(avg_hr))
    if max_hr is not None:
        device_metrics["maxHeartRate"] = round(float(max_hr))
    if session.get("avg_cadence") is not None:
        device_metrics["avgCadenceStepsPerMin"] = round(float(session["avg_cadence"]) * 2)
    if session.get("max_cadence") is not None:
        device_metrics["maxCadenceStepsPerMin"] = round(float(session["max_cadence"]) * 2)
    if session.get("calories") is not None:
        device_metrics["calories"] = round(float(session["calories"]))

    digest = hashlib.sha256(fit_bytes).hexdigest()[:24]
    if client_mutation_id:
        try:
            mutation_id = str(uuid.UUID(client_mutation_id))
        except ValueError:
            mutation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fit-upload:{client_mutation_id}"))
    else:
        mutation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fit-upload:{digest}"))
    provider_activity_id = digest

    # Guarantee zero GPS coordinates are persisted in samples or telemetry.
    clean_samples = {
        k: v
        for k, v in (tele.get("samples") or {}).items()
        if k in {"t", "d", "v", "hr", "cad"}
    }
    hr_peak_30s = peak_rolling_hr(clean_samples) if clean_samples.get("t") else None

    row_id = conn.execute(
        text(
            """
            INSERT INTO completed_activities (
                athlete_id, client_mutation_id, request_fingerprint,
                provider, provider_activity_id,
                duration_minutes, rpe, performed_at, timezone_snapshot,
                local_training_date, session_load, unit, source_metric,
                distance_km, device_metrics, structure
            ) VALUES (
                :athlete_id, :client_mutation_id, :request_fingerprint,
                'garmin', :provider_activity_id,
                :duration_minutes, :rpe, :performed_at, :timezone_snapshot,
                :local_training_date, :session_load, 'AU', :source_metric,
                :distance_km, CAST(:device_metrics AS jsonb), '[]'::jsonb
            )
            ON CONFLICT (athlete_id, client_mutation_id) DO UPDATE SET
                deleted_at = NULL,
                duration_minutes = EXCLUDED.duration_minutes,
                rpe = EXCLUDED.rpe,
                session_load = EXCLUDED.session_load,
                source_metric = EXCLUDED.source_metric,
                distance_km = EXCLUDED.distance_km,
                device_metrics = EXCLUDED.device_metrics
            RETURNING id
            """
        ),
        {
            "athlete_id": athlete_id,
            "client_mutation_id": mutation_id,
            "request_fingerprint": digest,
            "provider_activity_id": provider_activity_id,
            "duration_minutes": duration_minutes,
            "rpe": resolved_rpe,
            "performed_at": start_time,
            "timezone_snapshot": timezone_name,
            "local_training_date": local_training_date,
            "session_load": session_load,
            "source_metric": source_metric,
            "distance_km": distance_km,
            "device_metrics": json.dumps(device_metrics),
        },
    ).scalar_one()

    conn.execute(
        text("DELETE FROM athlete_rest_days WHERE athlete_id = :a AND date = :d"),
        {"a": athlete_id, "d": local_training_date},
    )

    conn.execute(
        text(
            """
            INSERT INTO activity_telemetry (
                activity_id, athlete_id, source, sport, sub_sport, device,
                hr_profile, laps, timer_events, workout_steps, samples,
                hr_peak_30s, activity_name
            ) VALUES (
                :activity_id, :athlete_id, 'garmin_fit', :sport, :sub_sport, :device,
                CAST(:hr_profile AS jsonb), CAST(:laps AS jsonb),
                CAST(:timer_events AS jsonb), CAST(:workout_steps AS jsonb),
                CAST(:samples AS jsonb), :hr_peak_30s, :activity_name
            )
            ON CONFLICT (activity_id) DO UPDATE SET
                sport = EXCLUDED.sport,
                sub_sport = EXCLUDED.sub_sport,
                device = EXCLUDED.device,
                hr_profile = EXCLUDED.hr_profile,
                laps = EXCLUDED.laps,
                timer_events = EXCLUDED.timer_events,
                workout_steps = EXCLUDED.workout_steps,
                samples = EXCLUDED.samples,
                hr_peak_30s = EXCLUDED.hr_peak_30s,
                activity_name = COALESCE(EXCLUDED.activity_name, activity_telemetry.activity_name)
            """
        ),
        {
            "activity_id": row_id,
            "athlete_id": athlete_id,
            "sport": tele.get("sport"),
            "sub_sport": tele.get("sub_sport"),
            "device": tele.get("device"),
            "hr_profile": json.dumps(hr_profile),
            "laps": json.dumps(tele.get("laps") or []),
            "timer_events": json.dumps(tele.get("timer_events") or []),
            "workout_steps": json.dumps(tele.get("workout_steps") or []),
            "samples": json.dumps(clean_samples),
            "hr_peak_30s": hr_peak_30s,
            "activity_name": activity_name,
        },
    )

    lock_athlete_training_load(conn, athlete_id)
    recompute_training_load(conn, athlete_id, local_training_date)

    return {
        "activity_id": str(row_id),
        "local_training_date": local_training_date.isoformat(),
        "duration_minutes": duration_minutes,
        "distance_km": distance_km,
        "rpe": resolved_rpe,
        "session_load": session_load,
        "unit": "AU",
        "source_metric": source_metric,
        "device": tele.get("device"),
        "laps_count": len(tele.get("laps") or []),
        "hr_peak_30s": hr_peak_30s,
        "gps_stored": False,
    }

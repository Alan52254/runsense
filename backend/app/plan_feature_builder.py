"""Build de-identified Plan-Ranking feature rows from an athlete's real history.

One decision per day the athlete has a Completed Activity (plus the rest-day
decisions in between): four bounded candidates (rest / recovery / easy / steady),
labelled 1 for the intensity that best matches what the athlete actually did.
Features come from that day's daily training-load row, any injury report, and --
for the current day only -- the live weather cache. Historical weather is not
retained, so older days fall back to the feature contract's defaults.

Nothing identifying leaves this module: dates become opaque ``time_index``
integers, the athlete is a single opaque ``group`` surrogate, and every feature
key is checked against the contract by :func:`FeatureRow` validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
import statistics
import uuid

from sqlalchemy import Connection, text

from app.climate_normals import get_climate_normal
from app.db import actor_transaction
from app.weather_pace import speed_loss_pct
from ml.feature_contract import FeatureRow, derive_interaction_features, validate_row

# Distance (km) / duration (min) per bounded candidate -- mirrors
# ml.synthetic._INTENSITY_PROFILE so real and synthetic rows are comparable.
_INTENSITY_PROFILE: dict[int, tuple[float, int]] = {
    0: (0.0, 0),
    1: (3.0, 22),
    2: (7.0, 40),
    3: (11.0, 58),
}
_SEVERITY_SORENESS = {"NONE": 0, "MILD": 1, "MODERATE": 2, "SEVERE": 3}


def observed_intensity(duration_minutes: float | None, rpe: int | None) -> int:
    """Bucket what the athlete actually did into a candidate intensity 0..3."""
    if duration_minutes is None or duration_minutes <= 0:
        return 0
    if rpe is not None and rpe >= 6:
        return 3
    if duration_minutes >= 55:
        return 3
    if duration_minutes <= 30 or (rpe is not None and rpe <= 3):
        return 1
    return 2


def _base_features(
    *,
    acute: float | None,
    chronic: float | None,
    load_ramp_pct: float | None = None,
    observation_days: int,
    days_since_last: int,
    session_count_7d: int,
    temp_c: float | None,
    temp_vs_normal_c: float | None = None,
    weather_actionable: bool,
    soreness: int,
    escalated: bool,
    self_care: bool,
    sex: str | None = None,
    humidity_pct: float | None = None,
    baseline_easy_pace_s_per_km: float | None = None,
    recent_avg_hr_bpm: float | None = None,
    avg_rpe_7d: float | None = None,
    resting_hr_delta: float | None = None,
    sleep_hours: float | None = None,
) -> dict[str, float]:
    ratio = None
    if acute is not None and chronic is not None and chronic > 0:
        ratio = acute / chronic
    f: dict[str, float] = {
        "observation_days": float(observation_days),
        "days_since_last_activity": float(min(days_since_last, 60)),
        "session_count_7d": float(session_count_7d),
        "weather_actionable": 1.0 if weather_actionable else 0.0,
        "triage_self_care": 1.0 if self_care else 0.0,
        "triage_escalated": 1.0 if escalated else 0.0,
        "soreness_ord": float(soreness),
    }
    if acute is not None:
        f["acute_load"] = float(acute)
    if chronic is not None:
        f["chronic_load"] = float(chronic)
    if ratio is not None:
        f["acute_chronic_ratio"] = round(ratio, 4)
    if load_ramp_pct is not None:
        f["load_ramp_pct"] = float(load_ramp_pct)
    if temp_c is not None:
        f["temp_c"] = float(temp_c)
        f["climate_speed_loss_pct"] = float(speed_loss_pct(float(temp_c), sex))
    if temp_vs_normal_c is not None:
        f["temp_vs_normal_c"] = float(temp_vs_normal_c)
    if sex is not None:
        f["sex_female"] = 1.0 if sex == "female" else 0.0
    if humidity_pct is not None:
        f["humidity_pct"] = float(humidity_pct)
    if baseline_easy_pace_s_per_km is not None:
        f["baseline_easy_pace_s_per_km"] = float(baseline_easy_pace_s_per_km)
    if recent_avg_hr_bpm is not None:
        f["recent_avg_hr_bpm"] = float(recent_avg_hr_bpm)
    if avg_rpe_7d is not None:
        f["avg_rpe_7d"] = float(avg_rpe_7d)
    if resting_hr_delta is not None:
        f["resting_hr_delta"] = float(resting_hr_delta)
    if sleep_hours is not None:
        f["sleep_hours"] = float(sleep_hours)
    return f


def build_history_feature_rows(
    tx,
    actor_id: uuid.UUID,
    *,
    max_days: int | None = 45,
    group: int = 0,
    query_id_start: int = 0,
    include_rest_days: bool = True,
    wellness_by_date: Mapping[date, tuple[float | None, float | None]] | None = None,
) -> list[FeatureRow]:
    if max_days is None:
        activities = tx.execute(
            text(
                "SELECT local_training_date, duration_minutes, distance_km, rpe "
                "FROM completed_activities "
                "WHERE athlete_id = :a AND deleted_at IS NULL "
                "ORDER BY local_training_date DESC"
            ),
            {"a": actor_id},
        ).fetchall()
    else:
        activities = tx.execute(
            text(
                "SELECT local_training_date, duration_minutes, distance_km, rpe "
                "FROM completed_activities "
                "WHERE athlete_id = :a AND deleted_at IS NULL "
                "ORDER BY local_training_date DESC LIMIT :n"
            ),
            {"a": actor_id, "n": max_days},
        ).fetchall()
    if not activities:
        return []
    activities = list(reversed(activities))  # oldest -> newest

    load_rows = tx.execute(
        text(
            "SELECT date, acute_load, chronic_load, observation_days "
            "FROM training_load_daily WHERE athlete_id = :a AND unit = 'AU' "
            "ORDER BY date"
        ),
        {"a": actor_id},
    ).fetchall()
    load_by_date = {r.date: r for r in load_rows}
    sorted_load_dates_desc = sorted(load_by_date, reverse=True)

    injuries = tx.execute(
        text(
            "SELECT local_training_date, severity_band FROM injury_reports "
            "WHERE athlete_id = :a"
        ),
        {"a": actor_id},
    ).fetchall()
    injury_by_date = {r.local_training_date: r.severity_band for r in injuries}

    profile = tx.execute(
        text(
            "SELECT sex, city FROM athlete_profiles WHERE user_id = :a LIMIT 1"
        ),
        {"a": actor_id},
    ).first()
    sex = getattr(profile, "sex", None) if profile is not None else None
    city = getattr(profile, "city", None) if profile is not None else None

    weather = None
    if city:
        weather = tx.execute(
            text(
                "SELECT temperature_c, humidity_pct, fetched_at "
                "FROM weather_cache WHERE city = :c "
                "ORDER BY fetched_at DESC LIMIT 1"
            ),
            {"c": city},
        ).first()

    rest_rows = tx.execute(
        text(
            "SELECT date FROM athlete_rest_days WHERE athlete_id = :a ORDER BY date"
        ),
        {"a": actor_id},
    ).fetchall()
    rest_dates = {r.date for r in rest_rows if getattr(r, "date", None) is not None}

    hr_rows = tx.execute(
        text(
            "SELECT a.local_training_date, (w.metrics->>'avg_hr')::float AS avg_hr "
            "FROM workout_analyses w "
            "JOIN completed_activities a ON a.id = w.activity_id "
            "WHERE w.athlete_id = :a AND a.deleted_at IS NULL "
            "AND w.metrics->>'avg_hr' IS NOT NULL "
            "ORDER BY a.local_training_date"
        ),
        {"a": actor_id},
    ).fetchall()
    hr_by_date: dict[date, list[float]] = {}
    for hr_row in hr_rows:
        d = getattr(hr_row, "local_training_date", None)
        val = getattr(hr_row, "avg_hr", None)
        if d is not None and val is not None:
            hr_by_date.setdefault(d, []).append(float(val))

    today = datetime.now(UTC).date()

    act_by_date: dict[date, list[object]] = {}
    for act in activities:
        act_by_date.setdefault(act.local_training_date, []).append(act)

    first_day = min(act_by_date)
    decision_dates = sorted(
        set(act_by_date.keys())
        | (
            {d for d in rest_dates if d >= first_day and d not in act_by_date}
            if include_rest_days
            else set()
        )
    )
    sorted_act_dates = sorted(act_by_date.keys())

    rows: list[FeatureRow] = []
    for idx, day in enumerate(decision_dates):
        day_acts = act_by_date.get(day)
        if day_acts is None:
            obs_int = 0
        else:
            tot_dur = sum(
                float(a.duration_minutes)
                for a in day_acts
                if getattr(a, "duration_minutes", None) is not None and float(a.duration_minutes) > 0
            )
            rpe_pairs = [
                (float(a.duration_minutes), float(a.rpe))
                for a in day_acts
                if getattr(a, "duration_minutes", None) is not None
                and float(a.duration_minutes) > 0
                and getattr(a, "rpe", None) is not None
            ]
            if tot_dur > 0 and rpe_pairs:
                w_rpe = round(sum(d * r for d, r in rpe_pairs) / sum(d for d, _ in rpe_pairs))
            elif day_acts[0].rpe is not None:
                w_rpe = int(day_acts[0].rpe)
            else:
                w_rpe = None
            obs_int = observed_intensity(tot_dur if tot_dur > 0 else None, w_rpe)

        # Strictly pre-decision (< day) daily-load row
        load = next(
            (load_by_date[d] for d in sorted_load_dates_desc if d < day),
            None,
        )
        prev_load = next(
            (load_by_date[d] for d in sorted_load_dates_desc if d <= day - timedelta(days=7)),
            None,
        )

        prev_act_day = next((d for d in reversed(sorted_act_dates) if d < day), None)
        days_since_last = (day - prev_act_day).days if prev_act_day is not None else 3

        window_start = day - timedelta(days=7)
        session_count_7d = sum(
            1
            for a in activities
            if window_start <= a.local_training_date < day
        )

        rpes_7d = [
            float(a.rpe)
            for a in activities
            if window_start <= a.local_training_date < day and getattr(a, "rpe", None) is not None
        ]
        avg_rpe_7d = round(statistics.fmean(rpes_7d), 2) if rpes_7d else None

        easy_start = day - timedelta(days=180)
        easy_paces = [
            float(a.duration_minutes) * 60.0 / float(a.distance_km)
            for a in activities
            if easy_start <= a.local_training_date < day
            and getattr(a, "rpe", None) is not None
            and a.rpe <= 4
            and getattr(a, "distance_km", None) is not None
            and float(a.distance_km) >= 2.0
            and getattr(a, "duration_minutes", None) is not None
            and float(a.duration_minutes) > 0
        ]
        baseline_easy = round(statistics.median(easy_paces), 1) if len(easy_paces) >= 3 else None

        hr_start = day - timedelta(days=28)
        recent_hrs = [
            val
            for d, vals in hr_by_date.items()
            if hr_start <= d < day
            for val in vals
        ]
        recent_avg_hr = round(statistics.fmean(recent_hrs), 1) if recent_hrs else None

        severity = injury_by_date.get(day, "NONE")
        soreness = _SEVERITY_SORENESS.get(severity, 0)
        escalated = severity == "SEVERE"
        self_care = severity in {"MILD", "MODERATE"}

        is_today = day == today and weather is not None
        temp_c = (
            float(weather.temperature_c)
            if is_today and getattr(weather, "temperature_c", None) is not None
            else None
        )
        temp_vs_normal = None
        if temp_c is not None and city:
            normal = get_climate_normal(city, day.month)
            if normal is not None:
                temp_vs_normal = round(temp_c - normal.mean_c, 2)

        # A daily-load row is only a meaningful acute/chronic signal once the
        # 28-day window has enough coverage; before that the ratio is dominated
        # by a near-zero chronic baseline. Below the bar we drop the load
        # features and let the contract defaults (ratio = 1.0) stand.
        load_usable = load is not None and (load.observation_days or 0) >= 14
        load_ramp = None
        if (
            load_usable
            and load.acute_load is not None
            and prev_load is not None
            and prev_load.acute_load is not None
            and float(prev_load.acute_load) > 0.0
        ):
            load_ramp = round(
                ((float(load.acute_load) - float(prev_load.acute_load)) / float(prev_load.acute_load)) * 100.0,
                2,
            )

        rhr_delta: float | None = None
        sleep_h: float | None = None
        if wellness_by_date is not None and day in wellness_by_date:
            rhr_delta, sleep_h = wellness_by_date[day]

        base = _base_features(
            acute=float(load.acute_load) if load_usable and load.acute_load is not None else None,
            chronic=float(load.chronic_load) if load_usable and load.chronic_load is not None else None,
            load_ramp_pct=load_ramp,
            observation_days=int(load.observation_days) if load else 0,
            days_since_last=days_since_last,
            session_count_7d=session_count_7d,
            temp_c=temp_c,
            temp_vs_normal_c=temp_vs_normal,
            weather_actionable=is_today,
            soreness=soreness,
            escalated=escalated,
            self_care=self_care,
            sex=sex,
            humidity_pct=(
                float(weather.humidity_pct)
                if is_today and getattr(weather, "humidity_pct", None) is not None
                else None
            ),
            baseline_easy_pace_s_per_km=baseline_easy,
            recent_avg_hr_bpm=recent_avg_hr,
            avg_rpe_7d=avg_rpe_7d,
            resting_hr_delta=rhr_delta,
            sleep_hours=sleep_h,
        )

        qid = int(query_id_start) + idx
        time_index = (day - first_day).days
        for intensity in (0, 1, 2, 3):
            dist, dur = _INTENSITY_PROFILE[intensity]
            feats = {
                **base,
                "candidate_distance_km": float(dist),
                "candidate_duration_min": float(dur),
                "candidate_intensity_ord": float(intensity),
            }
            feats.update(derive_interaction_features(feats))
            row = FeatureRow(
                group=int(group),
                time_index=int(time_index),
                query_id=qid,
                candidate_id=f"hist-{group}-{qid}-{intensity}",
                label=1 if intensity == obs_int else 0,
                features=feats,
            )
            validate_row(row)
            rows.append(row)
    return rows


def load_history_feature_rows(
    conn: Connection,
    actor_id: uuid.UUID,
    *,
    max_days: int | None = 45,
    group: int = 0,
    query_id_start: int = 0,
    include_rest_days: bool = True,
    wellness_by_date: Mapping[date, tuple[float | None, float | None]] | None = None,
) -> list[FeatureRow]:
    with actor_transaction(conn, str(actor_id)) as tx:
        return build_history_feature_rows(
            tx,
            actor_id,
            max_days=max_days,
            group=group,
            query_id_start=query_id_start,
            include_rest_days=include_rest_days,
            wellness_by_date=wellness_by_date,
        )

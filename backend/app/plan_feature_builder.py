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

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, text

from app.db import actor_transaction
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
    observation_days: int,
    days_since_last: int,
    session_count_7d: int,
    temp_c: float | None,
    weather_actionable: bool,
    soreness: int,
    escalated: bool,
    self_care: bool,
) -> dict[str, float]:
    ratio = None
    if acute is not None and chronic:
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
    if temp_c is not None:
        f["temp_c"] = float(temp_c)
    return f


def build_history_feature_rows(
    tx, actor_id: uuid.UUID, *, max_days: int = 45
) -> list[FeatureRow]:
    activities = tx.execute(
        text(
            "SELECT local_training_date, duration_minutes, rpe "
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

    injuries = tx.execute(
        text(
            "SELECT local_training_date, severity_band FROM injury_reports "
            "WHERE athlete_id = :a"
        ),
        {"a": actor_id},
    ).fetchall()
    injury_by_date = {r.local_training_date: r.severity_band for r in injuries}

    weather = tx.execute(
        text(
            "SELECT temperature_c, fetched_at FROM weather_cache w "
            "JOIN athlete_profiles p ON p.city = w.city "
            "WHERE p.user_id = :a ORDER BY fetched_at DESC LIMIT 1"
        ),
        {"a": actor_id},
    ).first()
    today = datetime.now(UTC).date()

    act_dates = [r.local_training_date for r in activities]
    rows: list[FeatureRow] = []
    for i, act in enumerate(activities):
        day = act.local_training_date
        obs_int = observed_intensity(
            float(act.duration_minutes) if act.duration_minutes is not None else None,
            act.rpe,
        )
        # nearest daily-load row on or before this day
        load = load_by_date.get(day) or next(
            (load_by_date[d] for d in sorted(load_by_date, reverse=True) if d <= day),
            None,
        )
        days_since_last = (day - act_dates[i - 1]).days if i > 0 else 3
        window_start = day - timedelta(days=7)
        session_count_7d = sum(1 for d in act_dates if window_start < d <= day)

        severity = injury_by_date.get(day, "NONE")
        soreness = _SEVERITY_SORENESS.get(severity, 0)
        escalated = severity == "SEVERE"
        self_care = severity in {"MILD", "MODERATE"}

        is_today = day == today and weather is not None
        # A daily-load row is only a meaningful acute/chronic signal once the
        # 28-day window has enough coverage; before that the ratio is dominated
        # by a near-zero chronic baseline. Below the bar we drop the load
        # features and let the contract defaults (ratio = 1.0) stand.
        load_usable = load is not None and (load.observation_days or 0) >= 14
        base = _base_features(
            acute=float(load.acute_load) if load_usable and load.acute_load is not None else None,
            chronic=float(load.chronic_load) if load_usable and load.chronic_load is not None else None,
            observation_days=int(load.observation_days) if load else 0,
            days_since_last=days_since_last,
            session_count_7d=session_count_7d,
            temp_c=float(weather.temperature_c) if is_today and weather.temperature_c is not None else None,
            weather_actionable=is_today,
            soreness=soreness,
            escalated=escalated,
            self_care=self_care,
        )

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
                group=0,
                time_index=i,
                query_id=i,
                candidate_id=f"hist-{i}-{intensity}",
                label=1 if intensity == obs_int else 0,
                features=feats,
            )
            validate_row(row)
            rows.append(row)
    return rows


def load_history_feature_rows(conn: Connection, actor_id: uuid.UUID, *, max_days: int = 45) -> list[FeatureRow]:
    with actor_transaction(conn, str(actor_id)) as tx:
        return build_history_feature_rows(tx, actor_id, max_days=max_days)

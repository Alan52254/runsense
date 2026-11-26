"""De-identified offline feature loader for Garmin Connect GDPR exports.

Reads ``dataset/*.zip`` strictly in-memory via :mod:`zipfile` without ever
extracting files to disk or accessing PII files (``customer.json``,
``user_contact.json``, names, emails, or GPS coordinates). Only physiological
and training-load signals conforming to :data:`ml.feature_contract.FEATURE_CONTRACT`
are emitted as :class:`ml.feature_contract.FeatureRow` instances.

All rolling features enforce strict pre-decision causality (``< day``) so no
same-day workout telemetry or target-correlated weather flags leak into rest vs.
run labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import statistics
import zipfile

from app.plan_feature_builder import _INTENSITY_PROFILE, observed_intensity
from app.weather_pace import speed_loss_pct
from ml.feature_contract import FeatureRow, derive_interaction_features, validate_row

_RUNNING_ACTIVITY_TYPES: frozenset[str] = frozenset({
    "running",
    "track_running",
    "treadmill_running",
    "trail_running",
})

_DISALLOWED_ARCHIVE_SUFFIXES: tuple[str, ...] = (
    "customer.json",
    "user_contact.json",
)


@dataclass(frozen=True)
class _ParsedRun:
    local_date: date
    duration_min: float
    distance_km: float
    rpe: int
    session_load: float
    avg_hr: float | None
    outdoor_temp_c: float | None


@dataclass(frozen=True)
class GarminDatasetStats:
    total_calendar_days: int
    emitted_decisions: int
    skipped_missing_rpe_days: int
    run_decisions: int
    rest_decisions: int
    intensity_counts: dict[int, int]
    rhr_days_loaded: int
    sleep_days_loaded: int
    sex: str | None


def _to_rpe(workout_rpe: float | int | None) -> int | None:
    if workout_rpe is None:
        return None
    return max(1, min(10, round(float(workout_rpe) / 10.0)))


def _activity_local_date(act: dict) -> date | None:
    local_ms = act.get("startTimeLocal")
    if local_ms is not None:
        return datetime.fromtimestamp(float(local_ms) / 1000.0, tz=timezone.utc).date()
    gmt_ms = act.get("beginTimestamp") or act.get("startTimeGmt")
    if gmt_ms is not None:
        return datetime.fromtimestamp(float(gmt_ms) / 1000.0, tz=timezone.utc).date()
    return None


def _parse_sex_from_archive(archive: zipfile.ZipFile) -> str | None:
    matches = [
        n
        for n in archive.namelist()
        if n.endswith("user_profile.json")
        and not any(n.lower().endswith(bad) for bad in _DISALLOWED_ARCHIVE_SUFFIXES)
    ]
    if not matches:
        return None
    with archive.open(matches[0]) as fh:
        data = json.load(fh)
    gender = str(data.get("gender") or "").strip().upper()
    if gender == "FEMALE":
        return "female"
    if gender == "MALE":
        return "male"
    return None


def _parse_runs_from_archive(
    archive: zipfile.ZipFile,
) -> tuple[dict[date, list[_ParsedRun]], set[date]]:
    matches = [n for n in archive.namelist() if n.endswith("_1_summarizedActivities.json")]
    if not matches:
        raise RuntimeError("No *_1_summarizedActivities.json found in Garmin archive")

    runs_by_day: dict[date, list[_ParsedRun]] = {}
    all_run_dates: set[date] = set()

    for name in matches:
        with archive.open(name) as fh:
            payload = json.load(fh)
        if not payload or not isinstance(payload, list):
            continue
        activities = payload[0].get("summarizedActivitiesExport") or []
        for act in activities:
            act_type = act.get("activityType")
            if act_type not in _RUNNING_ACTIVITY_TYPES:
                continue
            local_day = _activity_local_date(act)
            if local_day is None:
                continue

            # Track before RPE filtering so missing-RPE run days are skipped
            # rather than mislabeled as rest days.
            all_run_dates.add(local_day)

            rpe = _to_rpe(act.get("workoutRpe"))
            if rpe is None:
                continue
            duration_ms = float(act.get("duration") or 0.0)
            duration_min = duration_ms / 1000.0 / 60.0
            if duration_min <= 0.0:
                continue
            distance_km = float(act.get("distance") or 0.0) / 100_000.0
            avg_hr = float(act["avgHr"]) if act.get("avgHr") is not None else None
            outdoor_temp_c = (
                float(act["minTemperature"])
                if act_type != "treadmill_running" and act.get("minTemperature") is not None
                else None
            )
            runs_by_day.setdefault(local_day, []).append(
                _ParsedRun(
                    local_date=local_day,
                    duration_min=duration_min,
                    distance_km=distance_km,
                    rpe=rpe,
                    session_load=duration_min * float(rpe),
                    avg_hr=avg_hr,
                    outdoor_temp_c=outdoor_temp_c,
                )
            )

    return runs_by_day, all_run_dates


def _parse_rhr_from_archive(archive: zipfile.ZipFile) -> dict[date, float]:
    matches = [
        n
        for n in archive.namelist()
        if "UDSFile_" in Path(n).name and n.endswith(".json")
    ]
    rhr_by_day: dict[date, float] = {}
    for name in sorted(matches):
        with archive.open(name) as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            cal = entry.get("calendarDate")
            rhr = entry.get("currentDayRestingHeartRate")
            if cal and rhr is not None:
                rhr_by_day[date.fromisoformat(str(cal))] = float(rhr)
    return rhr_by_day


def _parse_sleep_from_archive(archive: zipfile.ZipFile) -> dict[date, float]:
    matches = [n for n in archive.namelist() if n.endswith("_sleepData.json")]
    sleep_by_day: dict[date, float] = {}
    for name in sorted(matches):
        with archive.open(name) as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            cal = entry.get("calendarDate")
            if not cal:
                continue  # skip empty {"retro": False} placeholders
            total_s = (
                float(entry.get("deepSleepSeconds") or 0.0)
                + float(entry.get("lightSleepSeconds") or 0.0)
                + float(entry.get("remSleepSeconds") or 0.0)
            )
            if total_s > 0.0:
                sleep_by_day[date.fromisoformat(str(cal))] = round(total_s / 3600.0, 2)
    return sleep_by_day


def _load_garmin_internal(
    zip_path: Path,
    *,
    group: int = 0,
    query_id_start: int = 0,
    include_rest_days: bool = True,
) -> tuple[list[FeatureRow], GarminDatasetStats]:
    if not zip_path.exists():
        raise FileNotFoundError(f"Garmin dataset archive not found: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        sex = _parse_sex_from_archive(archive)
        runs_by_day, all_run_dates = _parse_runs_from_archive(archive)
        rhr_by_day = _parse_rhr_from_archive(archive)
        sleep_by_day = _parse_sleep_from_archive(archive)

    if not all_run_dates:
        return [], GarminDatasetStats(
            total_calendar_days=0,
            emitted_decisions=0,
            skipped_missing_rpe_days=0,
            run_decisions=0,
            rest_decisions=0,
            intensity_counts={0: 0, 1: 0, 2: 0, 3: 0},
            rhr_days_loaded=len(rhr_by_day),
            sleep_days_loaded=len(sleep_by_day),
            sex=sex,
        )

    first_day = min(all_run_dates)
    last_day = max(all_run_dates)
    total_calendar_days = (last_day - first_day).days + 1

    # Pre-index daily aggregates for strictly causal (< day) rolling lookups.
    daily_load: dict[date, float] = {
        d: sum(r.session_load for r in runs) for d, runs in runs_by_day.items()
    }

    rows: list[FeatureRow] = []
    qid = int(query_id_start)
    skipped_missing_rpe_days = 0
    run_decisions = 0
    rest_decisions = 0
    intensity_counts: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}

    sorted_run_days_all = sorted(all_run_dates)

    for day_offset in range(total_calendar_days):
        day = first_day + timedelta(days=day_offset)

        if day in all_run_dates and day not in runs_by_day:
            skipped_missing_rpe_days += 1
            continue

        day_runs = runs_by_day.get(day)
        if day_runs is None:
            if not include_rest_days:
                continue
            obs_int = 0
            rest_decisions += 1
        else:
            tot_dur = sum(r.duration_min for r in day_runs)
            w_rpe = round(sum(r.duration_min * float(r.rpe) for r in day_runs) / tot_dur)
            obs_int = observed_intensity(tot_dur, w_rpe)
            run_decisions += 1

        intensity_counts[obs_int] = intensity_counts.get(obs_int, 0) + 1

        # Strictly pre-decision (< day) rolling training load
        observation_days = min(day_offset, 28)
        acute_7d = sum(
            daily_load.get(day - timedelta(days=k), 0.0) for k in range(1, 8)
        )
        chronic_28d = (
            sum(daily_load.get(day - timedelta(days=k), 0.0) for k in range(1, 29))
            / 4.0
        )
        acute_prev_7d = sum(
            daily_load.get(day - timedelta(days=k), 0.0) for k in range(8, 15)
        )

        load_usable = observation_days >= 14 and chronic_28d > 0.0
        acute_feat = round(acute_7d, 2) if load_usable else None
        chronic_feat = round(chronic_28d, 2) if load_usable else None
        ratio_feat = round(acute_7d / chronic_28d, 4) if load_usable else None
        ramp_feat = (
            round(((acute_7d - acute_prev_7d) / acute_prev_7d) * 100.0, 2)
            if load_usable and acute_prev_7d > 0.0
            else (0.0 if load_usable else None)
        )

        # Recency & 7-day activity stats strictly < day
        prev_run_day = next(
            (d for d in reversed(sorted_run_days_all) if d < day),
            None,
        )
        days_since_last = (day - prev_run_day).days if prev_run_day is not None else 3

        runs_7d = [
            r
            for k in range(1, 8)
            for r in runs_by_day.get(day - timedelta(days=k), ())
        ]
        session_count_7d = len(runs_7d)
        avg_rpe_7d = (
            round(statistics.fmean(float(r.rpe) for r in runs_7d), 2)
            if runs_7d
            else None
        )

        # 180-day easy-run pace baseline strictly < day
        easy_paces = [
            (r.duration_min * 60.0) / r.distance_km
            for k in range(1, 181)
            for r in runs_by_day.get(day - timedelta(days=k), ())
            if r.rpe <= 4 and r.distance_km >= 2.0 and r.duration_min > 0.0
        ]
        baseline_easy_pace = (
            round(statistics.median(easy_paces), 1) if len(easy_paces) >= 5 else None
        )

        # 28-day recent average HR strictly < day
        hrs_28d = [
            r.avg_hr
            for k in range(1, 29)
            for r in runs_by_day.get(day - timedelta(days=k), ())
            if r.avg_hr is not None
        ]
        recent_avg_hr = (
            round(statistics.fmean(hrs_28d), 1) if hrs_28d else None
        )

        # Morning/pre-run wellness: UDS resting HR delta vs 28d prior, sleep on wake-up morning
        resting_hr_delta: float | None = None
        if day in rhr_by_day:
            prior_rhrs = [
                rhr_by_day[day - timedelta(days=k)]
                for k in range(1, 29)
                if (day - timedelta(days=k)) in rhr_by_day
            ]
            if len(prior_rhrs) >= 7:
                resting_hr_delta = round(
                    rhr_by_day[day] - statistics.fmean(prior_rhrs), 2
                )

        sleep_hours = sleep_by_day.get(day)

        # Strictly causal outdoor temperature from [day-3, day-1] (never day D's own run)
        recent_outdoor_temps = [
            r.outdoor_temp_c
            for k in range(1, 4)
            for r in runs_by_day.get(day - timedelta(days=k), ())
            if r.outdoor_temp_c is not None
        ]
        if recent_outdoor_temps:
            temp_c: float | None = float(recent_outdoor_temps[0])  # latest day in [day-3, day-1]
            weather_actionable = 1.0
            prior_60d_temps = [
                r.outdoor_temp_c
                for k in range(1, 61)
                for r in runs_by_day.get(day - timedelta(days=k), ())
                if r.outdoor_temp_c is not None
            ]
            temp_vs_normal = (
                round(temp_c - statistics.median(prior_60d_temps), 2)
                if len(prior_60d_temps) >= 5
                else 0.0
            )
            climate_loss = float(speed_loss_pct(temp_c, sex))
        else:
            temp_c = None
            weather_actionable = 0.0
            temp_vs_normal = None
            climate_loss = None

        base: dict[str, float] = {
            "observation_days": float(observation_days),
            "days_since_last_activity": float(min(days_since_last, 60)),
            "session_count_7d": float(session_count_7d),
            "weather_actionable": weather_actionable,
            "triage_self_care": 0.0,
            "triage_escalated": 0.0,
            "soreness_ord": 0.0,
        }
        if acute_feat is not None:
            base["acute_load"] = acute_feat
        if chronic_feat is not None:
            base["chronic_load"] = chronic_feat
        if ratio_feat is not None:
            base["acute_chronic_ratio"] = ratio_feat
        if ramp_feat is not None:
            base["load_ramp_pct"] = ramp_feat
        if temp_c is not None:
            base["temp_c"] = temp_c
        if temp_vs_normal is not None:
            base["temp_vs_normal_c"] = temp_vs_normal
        if climate_loss is not None:
            base["climate_speed_loss_pct"] = climate_loss
        if sex is not None:
            base["sex_female"] = 1.0 if sex == "female" else 0.0
        if baseline_easy_pace is not None:
            base["baseline_easy_pace_s_per_km"] = baseline_easy_pace
        if recent_avg_hr is not None:
            base["recent_avg_hr_bpm"] = recent_avg_hr
        if avg_rpe_7d is not None:
            base["avg_rpe_7d"] = avg_rpe_7d
        if resting_hr_delta is not None:
            base["resting_hr_delta"] = resting_hr_delta
        if sleep_hours is not None:
            base["sleep_hours"] = sleep_hours

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
                time_index=int(day_offset),
                query_id=int(qid),
                candidate_id=f"garmin-{qid}-{intensity}",
                label=1 if intensity == obs_int else 0,
                features=feats,
            )
            validate_row(row)
            rows.append(row)

        qid += 1

    stats = GarminDatasetStats(
        total_calendar_days=total_calendar_days,
        emitted_decisions=run_decisions + rest_decisions,
        skipped_missing_rpe_days=skipped_missing_rpe_days,
        run_decisions=run_decisions,
        rest_decisions=rest_decisions,
        intensity_counts=intensity_counts,
        rhr_days_loaded=len(rhr_by_day),
        sleep_days_loaded=len(sleep_by_day),
        sex=sex,
    )
    return rows, stats


def load_garmin_feature_rows(
    zip_path: Path,
    *,
    group: int = 0,
    query_id_start: int = 0,
    include_rest_days: bool = True,
) -> list[FeatureRow]:
    """Load de-identified 30-feature rows from a Garmin Connect GDPR archive."""
    rows, _ = _load_garmin_internal(
        zip_path,
        group=group,
        query_id_start=query_id_start,
        include_rest_days=include_rest_days,
    )
    return rows


def load_garmin_dataset_with_stats(
    zip_path: Path,
    *,
    group: int = 0,
    query_id_start: int = 0,
    include_rest_days: bool = True,
) -> tuple[list[FeatureRow], GarminDatasetStats]:
    """Load de-identified Garmin rows along with summary counts (no PII)."""
    return _load_garmin_internal(
        zip_path,
        group=group,
        query_id_start=query_id_start,
        include_rest_days=include_rest_days,
    )

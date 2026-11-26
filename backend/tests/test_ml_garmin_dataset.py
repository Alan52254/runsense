"""Tests for de-identified in-memory Garmin GDPR dataset loader (F4)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import zipfile

import pytest

from ml.feature_contract import validate_row
from ml.garmin_dataset import load_garmin_dataset_with_stats, load_garmin_feature_rows
from ml.splits import assert_forward_time, athlete_grouped_forward_splits

_REAL_ZIP = Path(__file__).resolve().parents[2] / "dataset" / "86058e89-d062-4bd8-8683-ffdd66d30981_1.zip"


def _ms(d: date, hour: int = 7) -> int:
    dt = datetime(d.year, d.month, d.day, hour, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _build_synthetic_garmin_zip(zip_path: Path) -> date:
    """Create a minimal in-memory-compatible Garmin GDPR zip with edge cases."""
    d0 = date(2026, 1, 1)
    activities = []

    # Days 0..19: outdoor easy/recovery runs with RHR & sleep
    for k in range(20):
        day = d0 + timedelta(days=k)
        if k in {5, 12}:
            # Day 5: rest day (no activity); Day 12: missing-RPE run (should be skipped, not rest)
            if k == 12:
                activities.append({
                    "activityType": "running",
                    "startTimeLocal": _ms(day, 6),
                    "startTimeGmt": _ms(day, 6) - 8 * 3600 * 1000,
                    "duration": 2_400_000.0,
                    "distance": 600_000.0,
                    "workoutRpe": None,
                    "avgHr": 150.0,
                    "minTemperature": 21.0,
                })
            continue
        activities.append({
            "activityType": "running",
            "startTimeLocal": _ms(day, 6),
            "startTimeGmt": _ms(day, 6) - 8 * 3600 * 1000,
            "duration": 2_400_000.0,  # 40 min
            "distance": 700_000.0,    # 7.0 km
            "workoutRpe": 40,         # RPE 4
            "avgHr": 145.0 + (k % 3),
            "minTemperature": 20.0 + (k % 4),
        })

    # Day 15: second run on same day (multi-run aggregation) + treadmill run (no outdoor temp)
    d15 = d0 + timedelta(days=15)
    activities.append({
        "activityType": "treadmill_running",
        "startTimeLocal": _ms(d15, 18),
        "duration": 1_800_000.0,  # 30 min
        "distance": 500_000.0,
        "workoutRpe": 80,         # RPE 8 -> weighted RPE raises intensity to 3
        "avgHr": 168.0,
        "minTemperature": 33.0,   # must be ignored because treadmill
    })

    # Non-running activity (must be excluded)
    activities.append({
        "activityType": "strength_training",
        "startTimeLocal": _ms(d0 + timedelta(days=5), 10),
        "duration": 1_800_000.0,
        "distance": 0.0,
        "workoutRpe": None,
    })

    uds_entries = [
        {
            "calendarDate": (d0 + timedelta(days=k)).isoformat(),
            "currentDayRestingHeartRate": 45 + (1 if k == 18 else 0),
        }
        for k in range(20)
    ]

    sleep_entries = [
        {"retro": False},  # empty placeholder like real Garmin GDPR exports
        *[
            {
                "calendarDate": (d0 + timedelta(days=k)).isoformat(),
                "sleepWindowConfirmationType": "ENHANCED_CONFIRMED_FINAL",
                "deepSleepSeconds": 5400,
                "lightSleepSeconds": 18000,
                # omit remSleepSeconds on day 18 to test missing REM robustness
                **({} if k == 18 else {"remSleepSeconds": 3600}),
            }
            for k in range(20)
        ],
    ]

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "DI_CONNECT/DI-Connect-User/customer.json",
            json.dumps({"fullName": "DO NOT READ", "email": "pii@example.com"}),
        )
        zf.writestr(
            "DI_CONNECT/DI-Connect-User/user_contact.json",
            json.dumps({"email": "pii@example.com", "latitude": 25.03}),
        )
        zf.writestr(
            "DI_CONNECT/DI-Connect-User/user_profile.json",
            json.dumps({"gender": "FEMALE", "displayName": "IGNORED"}),
        )
        zf.writestr(
            "DI_CONNECT/DI-Connect-Fitness/test_1_summarizedActivities.json",
            json.dumps([{"summarizedActivitiesExport": activities}]),
        )
        zf.writestr(
            "DI_CONNECT/DI-Connect-Aggregator/UDSFile_2026-01-01.json",
            json.dumps(uds_entries),
        )
        zf.writestr(
            "DI_CONNECT/DI-Connect-Wellness/2026-01-01_sleepData.json",
            json.dumps(sleep_entries),
        )
    return d0


def test_garmin_loader_parses_in_memory_without_pii_and_enforces_causality(tmp_path: Path) -> None:
    zip_path = tmp_path / "garmin_sample.zip"
    _build_synthetic_garmin_zip(zip_path)

    rows, stats = load_garmin_dataset_with_stats(zip_path, group=3, query_id_start=50)

    assert stats.sex == "female"
    assert stats.total_calendar_days == 20
    assert stats.skipped_missing_rpe_days == 1  # day 12 skipped, NOT labeled rest
    assert stats.rest_decisions == 1            # day 5 rest
    assert stats.run_decisions == 18
    assert stats.emitted_decisions == 19
    assert len(rows) == 19 * 4

    for r in rows:
        validate_row(r)
        assert r.group == 3
        assert isinstance(r.query_id, int)
        assert r.query_id >= 50
        assert r.features["sex_female"] == 1.0

    # Group by time_index
    by_t: dict[int, list] = {}
    for r in rows:
        by_t.setdefault(r.time_index, []).append(r)

    # Missing-RPE day (t=12) must not be present
    assert 12 not in by_t

    # Rest day (t=5): label=1 on intensity 0, and causal weather_actionable=1 from prior outdoor runs
    rest_rows = by_t[5]
    rest_obs = next(int(r.features["candidate_intensity_ord"]) for r in rest_rows if r.label == 1)
    assert rest_obs == 0
    assert rest_rows[0].features["weather_actionable"] == 1.0

    # Day 0: no prior outdoor runs -> weather_actionable == 0.0 (no same-day temp leakage)
    assert by_t[0][0].features["weather_actionable"] == 0.0
    assert "temp_c" not in by_t[0][0].features

    # Day 15: multi-run weighted RPE (40*4 + 30*8)/70 = 5.71 -> 6 -> steady (3)
    d15_obs = next(int(r.features["candidate_intensity_ord"]) for r in by_t[15] if r.label == 1)
    assert d15_obs == 3

    # Day 18: RHR = 46 vs prior mean 45 -> +1.0; sleep without REM = (5400+18000)/3600 = 6.5h
    assert by_t[18][0].features["resting_hr_delta"] == pytest.approx(1.0)
    assert by_t[18][0].features["sleep_hours"] == pytest.approx(6.5)

    # include_rest_days=False excludes day 5
    no_rest_rows = load_garmin_feature_rows(zip_path, include_rest_days=False)
    assert len(no_rest_rows) == 18 * 4


def test_garmin_loader_raises_for_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_garmin_feature_rows(tmp_path / "does_not_exist.zip")


@pytest.mark.skipif(not _REAL_ZIP.exists(), reason="Real Garmin GDPR zip not present")
def test_real_garmin_archive_loads_cleanly_and_passes_forward_splits() -> None:
    rows, stats = load_garmin_dataset_with_stats(_REAL_ZIP, group=0, query_id_start=0)
    assert stats.total_calendar_days == 589
    assert stats.emitted_decisions == 588
    assert stats.skipped_missing_rpe_days == 1
    assert stats.run_decisions == 360
    assert stats.rest_decisions == 228
    assert len(rows) == 588 * 4
    assert all(stats.intensity_counts[i] > 0 for i in (0, 1, 2, 3))

    splits = athlete_grouped_forward_splits(rows, n_splits=4, gap=2)
    assert len(splits) == 4
    for sp in splits:
        assert_forward_time(rows, sp, gap=2)

from datetime import datetime, timedelta, timezone

from app.fingerprint import compute_request_fingerprint


def test_identical_payload_produces_identical_fingerprint():
    performed_at = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    fp1 = compute_request_fingerprint(45.0, 6, performed_at)
    fp2 = compute_request_fingerprint(45.0, 6, performed_at)
    assert fp1 == fp2


def test_timestamp_formatting_variance_does_not_change_fingerprint():
    """TC-IDEMPOTENCY-002: trailing Z vs +00:00 describe the same instant."""
    z_form = datetime.fromisoformat("2026-08-07T09:15:00+00:00")  # equivalent to "...Z"
    offset_form = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    assert z_form == offset_form  # sanity: same instant

    fp1 = compute_request_fingerprint(45.0, 6, z_form)
    fp2 = compute_request_fingerprint(45.0, 6, offset_form)
    assert fp1 == fp2


def test_different_timezone_same_instant_does_not_change_fingerprint():
    utc_form = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    plus_eight = timezone(timedelta(hours=8))
    local_form = datetime(2026, 8, 7, 17, 15, 0, tzinfo=plus_eight)  # same instant as utc_form
    assert utc_form == local_form

    fp1 = compute_request_fingerprint(45.0, 6, utc_form)
    fp2 = compute_request_fingerprint(45.0, 6, local_form)
    assert fp1 == fp2


def test_different_rpe_produces_different_fingerprint():
    performed_at = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    fp1 = compute_request_fingerprint(45.0, 6, performed_at)
    fp2 = compute_request_fingerprint(45.0, 7, performed_at)
    assert fp1 != fp2


def test_different_duration_produces_different_fingerprint():
    performed_at = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    fp1 = compute_request_fingerprint(45.0, 6, performed_at)
    fp2 = compute_request_fingerprint(46.0, 6, performed_at)
    assert fp1 != fp2


def test_different_instant_produces_different_fingerprint():
    fp1 = compute_request_fingerprint(45.0, 6, datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc))
    fp2 = compute_request_fingerprint(45.0, 6, datetime(2026, 8, 7, 9, 16, 0, tzinfo=timezone.utc))
    assert fp1 != fp2


def test_different_structure_produces_different_fingerprint():
    performed_at = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    fp1 = compute_request_fingerprint(45.0, 6, performed_at, [{"kind": "jog", "label": "慢跑"}])
    fp2 = compute_request_fingerprint(45.0, 6, performed_at, [{"kind": "interval", "label": "間歇"}])
    assert fp1 != fp2


def test_omitted_and_empty_structure_fingerprint_identically():
    performed_at = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    fp1 = compute_request_fingerprint(45.0, 6, performed_at)
    fp2 = compute_request_fingerprint(45.0, 6, performed_at, [])
    assert fp1 == fp2


def test_different_distance_km_produces_different_fingerprint():
    performed_at = datetime(2026, 8, 7, 9, 15, 0, tzinfo=timezone.utc)
    fp1 = compute_request_fingerprint(45.0, 6, performed_at, distance_km=8.0)
    fp2 = compute_request_fingerprint(45.0, 6, performed_at, distance_km=9.0)
    assert fp1 != fp2

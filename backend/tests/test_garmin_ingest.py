"""Unit and route tests for Garmin wellness ingestion, FIT HR-TRIMP, and M3 hardening."""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
import struct
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.garmin_ingest import (
    compute_hr_trimp_rpe,
    get_latest_wellness,
    get_wellness_trend,
    ingest_fit_activity,
    upsert_wellness_rows,
)
from app.main import app


def _fit_crc(data: bytes) -> int:
    crc_table = (
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
    )
    crc = 0
    for byte in data:
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[byte & 0xF]
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[(byte >> 4) & 0xF]
    return crc


def _fit_def(local: int, global_mesg: int, fields: list[tuple[int, int, int]]) -> bytes:
    header = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_mesg, len(fields))
    body = b"".join(struct.pack("<BBB", fid, size, base_type) for fid, size, base_type in fields)
    return header + body


def _build_local_fit_bytes(*, duration_s: int = 1200, avg_hr: int = 152, distance_m: float = 4000.0) -> bytes:
    """Build a minimal valid FIT binary payload locally (including raw lat/lon to test stripping)."""
    fit_epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    start_ts = int((datetime(2026, 11, 20, 6, 30, tzinfo=timezone.utc) - fit_epoch).total_seconds())
    records = bytearray()

    # 0: file_id (global 0)
    records.extend(_fit_def(0, 0, [(0, 1, 0), (1, 2, 132), (2, 2, 132)]))
    records.extend(struct.pack("<BBHH", 0, 4, 1, 4432))

    # 1: record (global 20) including GPS position_lat / position_long to verify stripping
    records.extend(
        _fit_def(
            1,
            20,
            [(253, 4, 134), (0, 4, 133), (1, 4, 133), (3, 1, 2), (5, 4, 134)],
        )
    )
    lat_sc = int(25.0330 / 180.0 * 2147483648.0)
    lon_sc = int(121.5654 / 180.0 * 2147483648.0)
    for step in range(10):
        records.extend(
            struct.pack("<BIiiBI", 1, start_ts + step, lat_sc, lon_sc, avg_hr, step * 300)
        )

    # 2: session (global 18)
    records.extend(
        _fit_def(
            2,
            18,
            [(253, 4, 134), (2, 4, 134), (7, 4, 134), (8, 4, 134), (9, 4, 134), (5, 1, 0), (16, 1, 2)],
        )
    )
    records.extend(
        struct.pack(
            "<BIIIIIBB",
            2,
            start_ts + duration_s,
            start_ts,
            duration_s * 1000,
            duration_s * 1000,
            int(distance_m * 100),
            1,
            avg_hr,
        )
    )

    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(records), b".FIT")
    header += struct.pack("<H", _fit_crc(header[:12]))
    body = bytes(records)
    return header + body + struct.pack("<H", _fit_crc(header + body))


def test_compute_hr_trimp_rpe_clamps_and_distinguishes_fallback() -> None:
    rpe_missing, load_missing, src_missing = compute_hr_trimp_rpe(30.0, None)
    assert src_missing == "DURATION_DEFAULT"
    assert rpe_missing == 4
    assert load_missing == 120.0

    rpe_easy, _, src_easy = compute_hr_trimp_rpe(40.0, 128.0, 190.0, 55.0, sex="male")
    rpe_hard, _, src_hard = compute_hr_trimp_rpe(40.0, 178.0, 190.0, 55.0, sex="male")
    assert src_easy == "HR_TRIMP" and src_hard == "HR_TRIMP"
    assert 1 <= rpe_easy < rpe_hard <= 10

    rpe_max, _, _ = compute_hr_trimp_rpe(90.0, 225.0, 190.0, 50.0, sex="female")
    assert rpe_max == 10


def test_upsert_wellness_rejects_pii_and_gps_keys() -> None:
    class _DummyConn:
        def execute(self, *_a, **_kw):
            raise AssertionError("Should reject before executing SQL")

    for bad_key in ("email", "lat", "lon", "position_lat", "gps"):
        try:
            upsert_wellness_rows(
                _DummyConn(),
                uuid.uuid4(),
                [{"local_date": "2026-11-20", bad_key: 123}],
            )
            raise AssertionError(f"Expected ValueError for {bad_key}")
        except ValueError:
            pass


def test_get_latest_wellness_and_trend_handle_missing_table_gracefully() -> None:
    from sqlalchemy.exc import ProgrammingError

    class _Nested:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _ErrConn:
        def begin_nested(self):
            return _Nested()

        def execute(self, *_a, **_kw):
            raise ProgrammingError("SELECT", {}, Exception("undefined_table"))

    aid = uuid.uuid4()
    assert get_latest_wellness(_ErrConn(), aid, on_date=date(2026, 11, 20)) is None
    assert get_wellness_trend(_ErrConn(), aid, on_date=date(2026, 11, 20), days=7) == []


def test_garmin_routes_registered_and_reject_corrupt_fit(monkeypatch) -> None:
    from app.routes import garmin as garmin_routes
    from app.db import get_connection

    actor = str(uuid.uuid4())

    class _ActorProvider:
        def get_current_actor_id(self) -> str:
            return actor

    class _TzProvider:
        def get_profile_timezone(self, _actor_id: str) -> str:
            return "Asia/Taipei"

    app.dependency_overrides[get_connection] = lambda: object()
    app.dependency_overrides[garmin_routes.get_current_actor_provider] = lambda: _ActorProvider()
    app.dependency_overrides[garmin_routes.get_profile_timezone_provider] = lambda: _TzProvider()

    class _FakeTx:
        def execute(self, sql, params=None):
            s = str(sql)
            class _R:
                def first(self_inner):
                    return SimpleNamespace(sex="male") if "athlete_profiles" in s else None
                def scalar_one(self_inner):
                    return uuid.uuid4()
            return _R()

    monkeypatch.setattr(garmin_routes, "actor_transaction", lambda _c, _a: _Ctx(_FakeTx()))
    try:
        client = TestClient(app)
        paths = client.get("/openapi.json").json()["paths"]
        assert "/garmin/wellness/latest" in paths
        assert "/garmin/wellness/trend" in paths
        assert "/garmin/wellness/import" in paths
        assert "/garmin/fit/upload" in paths

        bad_b64 = base64.b64encode(b"CORRUPT_FIT").decode("ascii")
        res = client.post("/garmin/fit/upload", json={"fit_base64": bad_b64})
        assert res.status_code == 422
        assert res.json()["detail"]["error"] == "INVALID_FIT_FILE"
    finally:
        app.dependency_overrides.clear()


class _Ctx:
    def __init__(self, tx):
        self._tx = tx

    def __enter__(self):
        return self._tx

    def __exit__(self, *_args):
        return False


def test_ingest_fit_activity_strips_gps_and_computes_hr_trimp() -> None:
    recorded_params: list[tuple[str, dict]] = []
    activity_uuid = uuid.uuid4()

    class _FakeConn:
        def execute(self, sql, params=None):
            sql_text = str(sql)
            recorded_params.append((sql_text, dict(params or {})))
            class _Res:
                def scalar_one(self_inner):
                    return activity_uuid
                def first(self_inner):
                    return None
                def all(self_inner):
                    return []
                def scalars(self_inner):
                    return []
            return _Res()

    fit_bytes = _build_local_fit_bytes(duration_s=1500, avg_hr=158, distance_m=5000.0)
    # Monkeypatch recompute_training_load + lock_athlete_training_load for unit isolation
    import app.garmin_ingest as gi
    orig_lock = gi.lock_athlete_training_load
    orig_recompute = gi.recompute_training_load
    gi.lock_athlete_training_load = lambda _c, _a: None
    gi.recompute_training_load = lambda _c, _a, _d: None
    try:
        out = ingest_fit_activity(
            _FakeConn(),
            uuid.uuid4(),
            fit_bytes,
            rpe=None,
            timezone_name="Asia/Taipei",
        )
    finally:
        gi.lock_athlete_training_load = orig_lock
        gi.recompute_training_load = orig_recompute

    assert out["source_metric"] == "HR_TRIMP"
    assert 1 <= out["rpe"] <= 10
    assert out["gps_stored"] is False

    telemetry_inserts = [p for s, p in recorded_params if "INSERT INTO activity_telemetry" in s]
    assert len(telemetry_inserts) == 1
    samples_json = telemetry_inserts[0]["samples"]
    assert "route_points" not in samples_json
    assert "lat" not in samples_json and "lon" not in samples_json

"""Days without a run inside a synced watch's period count as observed rest."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from app.training_load_store import _device_observed_rest_dates


class _Conn:
    def __init__(self, first, last):
        self.row = SimpleNamespace(first_day=first, last_day=last)

    def execute(self, *_args, **_kwargs):
        return SimpleNamespace(first=lambda: self.row)


def test_period_runs_from_first_watch_run_to_a_week_after_the_last():
    conn = _Conn(date(2026, 9, 1), date(2026, 9, 10))
    days = _device_observed_rest_dates(conn, uuid.uuid4(), date(2026, 8, 20), date(2026, 9, 30))
    assert min(days) == date(2026, 9, 1)
    assert max(days) == date(2026, 9, 17)
    assert len(days) == 17


def test_manual_only_athlete_gets_no_implied_rest_days():
    conn = _Conn(None, None)
    assert _device_observed_rest_dates(conn, uuid.uuid4(), date(2026, 8, 1), date(2026, 9, 30)) == set()

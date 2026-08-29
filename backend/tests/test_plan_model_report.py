"""Unit coverage for the offline Plan-Ranking model report.

Avoids a live DB: fakes the actor transaction and asserts the report shape,
the per-athlete determinism of the evaluation seed, and the guardrail flags.
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace

import app.plan_model_report as mod
from app.plan_model_report import PlanModelReportService, _history_summary


class _Result:
    def __init__(self, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def first(self):
        return self._first

    def fetchall(self):
        return self._rows


class _FakeTx:
    """First two execute() calls feed _history_summary; anything after is a
    plan_feature_builder query and returns no rows (no activity history)."""

    def __init__(self, load_row, activity_row):
        self._first_rows = [load_row, activity_row]
        self.calls = 0

    def execute(self, statement, params):  # noqa: ARG002
        self.calls += 1
        if self.calls <= 2:
            return _Result(first=self._first_rows[self.calls - 1])
        return _Result(rows=[])


def test_history_summary_derives_ratio_and_recency_from_rows():
    load = SimpleNamespace(acute_load=420.0, chronic_load=350.0, observation_days=28, date=None)
    from datetime import date

    activity = SimpleNamespace(n=140, last_date=date(2026, 8, 20), first_date=date(2026, 5, 1))

    summary = _history_summary(_FakeTx(load, activity), uuid.uuid4())

    assert summary["completed_activities"] == 140
    assert summary["acute_chronic_ratio"] == 1.2
    assert summary["observation_days"] == 28
    assert summary["history_span_days"] == (date(2026, 8, 20) - date(2026, 5, 1)).days


def test_report_is_deterministic_per_athlete_and_never_declares_a_winner(monkeypatch):
    load = SimpleNamespace(acute_load=300.0, chronic_load=300.0, observation_days=40, date=None)
    activity = SimpleNamespace(n=50, last_date=None, first_date=None)

    @contextlib.contextmanager
    def fake_txn(_conn, _actor):
        yield _FakeTx(load, activity)

    monkeypatch.setattr(mod, "actor_transaction", fake_txn)

    actor = uuid.UUID("11111111-1111-1111-1111-111111111111")
    a = PlanModelReportService(object()).get_report(actor)
    b = PlanModelReportService(object()).get_report(actor)

    assert a["winner_declared"] is False
    assert a["production_ranker"] == "deterministic-plan-ranker-v2"
    assert a["evaluation"]["winner_declared"] is False
    assert a["evaluation"]["n_rows"] > 0
    assert "baseline_aggregate" in a["evaluation"]
    # Same athlete -> identical evaluation (seed is derived from the actor id).
    assert a["evaluation"]["baseline_aggregate"] == b["evaluation"]["baseline_aggregate"]

    other = PlanModelReportService(object()).get_report(
        uuid.UUID("22222222-2222-2222-2222-222222222222")
    )
    assert other["evaluation"]["splits"] != a["evaluation"]["splits"] or (
        other["evaluation"]["baseline_aggregate"] != a["evaluation"]["baseline_aggregate"]
    )

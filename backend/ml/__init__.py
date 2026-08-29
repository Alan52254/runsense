"""Offline ML scaffold for RunSense Plan Ranking experiments.

This package is *offline only*. It never touches production request paths,
never imports from ``app``, and never reads athlete-owned data, database
contents, ``.env`` files, or provider exports. Every experiment in here runs
on de-identified synthetic fixtures (see :mod:`ml.synthetic`).

Guardrails encoded here (see ``docs/adr/0002-rank-bounded-training-plan-candidates.md``
and ``openspec/changes/health-training-intelligence``):

* A learned ranker may only *reorder* supplied candidates. It never invents or
  edits distance, duration, pace, or intensity.
* Evaluation uses athlete-grouped forward-time splits with a gap. No later
  observation from an athlete may sit in training before an earlier test
  observation from any athlete.
* Probability-flavoured output must be calibrated before it is shown, and the
  ranker must be able to abstain to deterministic ordering.
* No learned model is declared a winner or enabled by default. Production
  Plan Ranking stays deterministic until a locked, leakage-safe benchmark
  says otherwise.
"""

from __future__ import annotations

__all__ = [
    "feature_contract",
    "splits",
    "logistic_regression",
    "tree_adapters",
    "calibration",
    "metrics",
    "abstention",
    "ranker",
    "synthetic",
]

"""Probability calibration and calibration error, pure standard library.

Many strong classifiers emit distorted probabilities. Before any
probability-flavoured signal is shown to an athlete it must be calibrated.
Platt scaling (a 1-D logistic fit on the raw scores) is the default here
because it needs far less held-out data than isotonic regression -- the right
trade-off for RunSense's small cohort.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


class PlattCalibrator:
    """Fits ``p_calibrated = sigmoid(a * score + b)`` by gradient descent."""

    def __init__(self, *, learning_rate: float = 0.5, epochs: int = 800) -> None:
        self.learning_rate = float(learning_rate)
        self.epochs = int(epochs)
        self.a: float = 1.0
        self.b: float = 0.0
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> "PlattCalibrator":
        n = len(scores)
        if n == 0:
            raise ValueError("cannot calibrate on an empty set")
        if len(labels) != n:
            raise ValueError("scores and labels length mismatch")
        s = [float(v) for v in scores]
        y = [float(v) for v in labels]
        a, b = 1.0, 0.0
        lr = self.learning_rate
        for _ in range(self.epochs):
            ga = gb = 0.0
            for si, yi in zip(s, y):
                err = _sigmoid(a * si + b) - yi
                ga += err * si
                gb += err
            a -= lr * ga / n
            b -= lr * gb / n
        self.a, self.b = a, b
        self._fitted = True
        return self

    def transform(self, scores: Sequence[float]) -> list[float]:
        if not self._fitted:
            raise RuntimeError("calibrator is not fitted")
        return [_sigmoid(self.a * float(v) + self.b) for v in scores]


class IdentityCalibrator:
    """Pass-through calibrator, for baselines that are already probabilities."""

    fitted = True

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> "IdentityCalibrator":
        return self

    def transform(self, scores: Sequence[float]) -> list[float]:
        return [min(1.0, max(0.0, float(v))) for v in scores]


def expected_calibration_error(
    probs: Sequence[float], labels: Sequence[int], *, n_bins: int = 10
) -> float:
    """Bucketed |confidence - accuracy|, weighted by bin population. In [0, 1]."""

    n = len(probs)
    if n == 0:
        raise ValueError("need at least one prediction")
    if len(labels) != n:
        raise ValueError("probs and labels length mismatch")
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")

    bin_tot = [0] * n_bins
    bin_pos = [0.0] * n_bins
    bin_conf = [0.0] * n_bins
    for p, y in zip(probs, labels):
        pc = min(1.0, max(0.0, float(p)))
        idx = min(n_bins - 1, int(pc * n_bins))
        bin_tot[idx] += 1
        bin_pos[idx] += float(y)
        bin_conf[idx] += pc

    ece = 0.0
    for k in range(n_bins):
        if bin_tot[k] == 0:
            continue
        acc = bin_pos[k] / bin_tot[k]
        conf = bin_conf[k] / bin_tot[k]
        ece += (bin_tot[k] / n) * abs(acc - conf)
    return ece


def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float:
    n = len(probs)
    if n == 0:
        raise ValueError("need at least one prediction")
    return sum((float(p) - float(y)) ** 2 for p, y in zip(probs, labels)) / n


def reliability_table(
    probs: Sequence[float], labels: Sequence[int], *, n_bins: int = 10
) -> list[dict[str, float]]:
    n = len(probs)
    rows: list[dict[str, float]] = []
    bin_tot = [0] * n_bins
    bin_pos = [0.0] * n_bins
    bin_conf = [0.0] * n_bins
    for p, y in zip(probs, labels):
        pc = min(1.0, max(0.0, float(p)))
        idx = min(n_bins - 1, int(pc * n_bins))
        bin_tot[idx] += 1
        bin_pos[idx] += float(y)
        bin_conf[idx] += pc
    for k in range(n_bins):
        if bin_tot[k] == 0:
            continue
        rows.append(
            {
                "bin_lower": k / n_bins,
                "bin_upper": (k + 1) / n_bins,
                "count": float(bin_tot[k]),
                "mean_confidence": bin_conf[k] / bin_tot[k],
                "empirical_rate": bin_pos[k] / bin_tot[k],
                "weight": bin_tot[k] / n,
            }
        )
    return rows

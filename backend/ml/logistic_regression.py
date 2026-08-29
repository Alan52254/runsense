"""L2-regularised logistic regression, pure standard library.

This is the accountable, independently-reviewable baseline required before any
tree model is even benchmarked (see the research note, section 7). It has no
dependency on numpy, pandas, scikit-learn, or anything outside the standard
library, so it runs anywhere the backend runs.

Training is full-batch gradient descent on standardised features, which is
fully deterministic -- two fits on the same data give identical weights with
no seed needed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Vector = Sequence[float]
Matrix = Sequence[Vector]


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class _Standardizer:
    """Per-column mean/std standardisation. Constant columns pass through."""

    def __init__(self) -> None:
        self.means: list[float] = []
        self.stds: list[float] = []

    def fit(self, X: Matrix) -> "_Standardizer":
        n = len(X)
        if n == 0:
            raise ValueError("cannot standardise an empty matrix")
        d = len(X[0])
        self.means = [0.0] * d
        self.stds = [1.0] * d
        for j in range(d):
            col = [float(row[j]) for row in X]
            mean = sum(col) / n
            var = sum((v - mean) ** 2 for v in col) / n
            std = math.sqrt(var)
            self.means[j] = mean
            self.stds[j] = std if std > 1e-12 else 1.0
        return self

    def transform(self, X: Matrix) -> list[list[float]]:
        return [
            [(float(row[j]) - self.means[j]) / self.stds[j] for j in range(len(self.means))]
            for row in X
        ]


class LogisticRegressionBaseline:
    """Binary logistic regression fit by deterministic gradient descent."""

    def __init__(
        self,
        *,
        l2: float = 1.0,
        learning_rate: float = 0.1,
        epochs: int = 500,
        feature_names: Sequence[str] | None = None,
    ) -> None:
        if l2 < 0:
            raise ValueError("l2 must be >= 0")
        if learning_rate <= 0:
            raise ValueError("learning_rate must be > 0")
        if epochs < 1:
            raise ValueError("epochs must be >= 1")
        self.l2 = float(l2)
        self.learning_rate = float(learning_rate)
        self.epochs = int(epochs)
        self.feature_names = list(feature_names) if feature_names is not None else None
        self._scaler = _Standardizer()
        self.weights: list[float] = []
        self.bias: float = 0.0
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, X: Matrix, y: Sequence[int]) -> "LogisticRegressionBaseline":
        n = len(X)
        if n == 0:
            raise ValueError("cannot fit on an empty dataset")
        if len(y) != n:
            raise ValueError("X and y length mismatch")
        d = len(X[0])
        if any(len(row) != d for row in X):
            raise ValueError("ragged feature matrix")
        if self.feature_names is not None and len(self.feature_names) != d:
            raise ValueError("feature_names length does not match X width")

        Xs = self._scaler.fit(X).transform(X)
        w = [0.0] * d
        b = 0.0
        labels = [float(v) for v in y]
        lr = self.learning_rate
        lam = self.l2

        for _ in range(self.epochs):
            grad_w = [0.0] * d
            grad_b = 0.0
            for row, label in zip(Xs, labels):
                z = b + sum(w[j] * row[j] for j in range(d))
                err = _sigmoid(z) - label
                grad_b += err
                for j in range(d):
                    grad_w[j] += err * row[j]
            grad_b /= n
            for j in range(d):
                grad_w[j] = grad_w[j] / n + lam * w[j] / n
                w[j] -= lr * grad_w[j]
            b -= lr * grad_b

        self.weights = w
        self.bias = b
        self._fitted = True
        return self

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("model is not fitted")

    def predict_proba(self, X: Matrix) -> list[float]:
        self._require_fitted()
        Xs = self._scaler.transform(X)
        d = len(self.weights)
        return [
            _sigmoid(self.bias + sum(self.weights[j] * row[j] for j in range(d)))
            for row in Xs
        ]

    def predict(self, X: Matrix, *, threshold: float = 0.5) -> list[int]:
        return [1 if p >= threshold else 0 for p in self.predict_proba(X)]

    def coefficients(self) -> dict[str, float]:
        """Standardised-space weights, keyed by feature name when known."""

        self._require_fitted()
        names = self.feature_names or [f"x{j}" for j in range(len(self.weights))]
        out = {name: self.weights[j] for j, name in enumerate(names)}
        out["__bias__"] = self.bias
        return out

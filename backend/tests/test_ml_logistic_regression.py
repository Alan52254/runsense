"""Pure-stdlib logistic-regression baseline."""

from __future__ import annotations

import random

import pytest

from ml.logistic_regression import LogisticRegressionBaseline


def _separable(n: int = 240, seed: int = 0):
    rng = random.Random(seed)
    X, y = [], []
    for _ in range(n):
        label = rng.randint(0, 1)
        centre = 2.0 if label else -2.0
        X.append([rng.gauss(centre, 1.0), rng.gauss(centre * 0.5, 1.0), rng.gauss(0, 1.0)])
        y.append(label)
    return X, y


def test_module_has_no_heavy_imports():
    import ml.logistic_regression as m

    assert "numpy" not in getattr(m, "__dict__", {})
    assert "sklearn" not in str(m.__file__)  # sanity only


def test_learns_a_separable_pattern():
    X, y = _separable()
    model = LogisticRegressionBaseline(l2=0.5, epochs=400).fit(X, y)
    preds = model.predict(X)
    acc = sum(int(p == t) for p, t in zip(preds, y)) / len(y)
    assert acc > 0.9


def test_is_deterministic():
    X, y = _separable(seed=3)
    a = LogisticRegressionBaseline(epochs=200).fit(X, y)
    b = LogisticRegressionBaseline(epochs=200).fit(X, y)
    assert a.weights == b.weights
    assert a.bias == b.bias


def test_probabilities_in_unit_interval():
    X, y = _separable()
    model = LogisticRegressionBaseline().fit(X, y)
    assert all(0.0 <= p <= 1.0 for p in model.predict_proba(X))


def test_coefficients_are_named():
    X, y = _separable()
    names = ["a", "b", "c"]
    model = LogisticRegressionBaseline(feature_names=names).fit(X, y)
    coefs = model.coefficients()
    assert set(names) <= set(coefs)
    assert "__bias__" in coefs
    # feature 0 drives the label most.
    assert abs(coefs["a"]) >= abs(coefs["c"])


def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError):
        LogisticRegressionBaseline().predict_proba([[0.0, 0.0, 0.0]])


def test_bad_hyperparams_raise():
    with pytest.raises(ValueError):
        LogisticRegressionBaseline(l2=-1)
    with pytest.raises(ValueError):
        LogisticRegressionBaseline(learning_rate=0)
    with pytest.raises(ValueError):
        LogisticRegressionBaseline(epochs=0)


def test_ragged_matrix_raises():
    with pytest.raises(ValueError):
        LogisticRegressionBaseline().fit([[1.0, 2.0], [3.0]], [0, 1])

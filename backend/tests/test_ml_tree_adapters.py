"""Optional tree adapters skip cleanly when the package is absent."""

from __future__ import annotations

import random

import pytest

from ml.tree_adapters import (
    CatBoostRankerAdapter,
    OptionalDependencyMissing,
    XGBoostRankerAdapter,
    available_tree_adapters,
    build_tree_adapter,
    catboost_available,
    maybe_build_tree_adapter,
    xgboost_available,
)


def _xy(n=120, seed=0):
    rng = random.Random(seed)
    X, y = [], []
    for _ in range(n):
        label = rng.randint(0, 1)
        X.append([rng.gauss(label, 1.0), rng.gauss(0, 1.0)])
        y.append(label)
    return X, y


def test_availability_probes_return_bool():
    for name, flag in available_tree_adapters().items():
        assert name in {"xgboost", "catboost"}
        assert isinstance(flag, bool)


def test_maybe_build_none_is_none():
    assert maybe_build_tree_adapter(None) is None
    assert maybe_build_tree_adapter("none") is None


def test_unknown_adapter_name_raises():
    with pytest.raises(ValueError):
        maybe_build_tree_adapter("lightgbm")
    with pytest.raises(ValueError):
        build_tree_adapter("lightgbm")


@pytest.mark.parametrize(
    "cls,available",
    [(XGBoostRankerAdapter, xgboost_available()), (CatBoostRankerAdapter, catboost_available())],
)
def test_build_matches_availability(cls, available):
    if available:
        adapter = cls()
        X, y = _xy()
        adapter.fit(X, y)
        probs = adapter.predict_proba(X)
        assert len(probs) == len(X)
        assert all(0.0 <= p <= 1.0 for p in probs)
    else:
        with pytest.raises(OptionalDependencyMissing) as exc:
            cls()
        assert cls.package_name in str(exc.value)
        # maybe_build swallows the missing dependency and returns None.
        assert maybe_build_tree_adapter(cls.name) is None


def test_missing_message_is_actionable():
    if xgboost_available():
        pytest.skip("xgboost installed in this environment")
    with pytest.raises(OptionalDependencyMissing) as exc:
        XGBoostRankerAdapter()
    msg = str(exc.value)
    assert "not installed" in msg and "maybe_build_tree_adapter" in msg

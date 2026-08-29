"""Optional gradient-boosted-tree adapters.

XGBoost and CatBoost are *not* backend dependencies. These adapters import
them lazily and, when the package is absent, either raise a clear
:class:`OptionalDependencyMissing` (explicit build) or return ``None``
(``maybe_build_*``) so callers can skip cleanly.

Per ADR 0002 and the research note, a tree model is only ever a *benchmark
candidate*. It reorders supplied candidates exactly like the baseline; it is
never enabled by default and never declared a winner here.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence

Vector = Sequence[float]
Matrix = Sequence[Vector]


class OptionalDependencyMissing(RuntimeError):
    """Raised when a tree adapter is built but its package is not installed."""


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def xgboost_available() -> bool:
    return _module_available("xgboost")


def catboost_available() -> bool:
    return _module_available("catboost")


def available_tree_adapters() -> dict[str, bool]:
    return {"xgboost": xgboost_available(), "catboost": catboost_available()}


class _BaseTreeAdapter:
    package_name: str = ""
    name: str = ""

    def __init__(self, *, params: dict[str, object] | None = None, num_rounds: int = 200) -> None:
        if not _module_available(self.package_name):
            raise OptionalDependencyMissing(
                f"{self.name} adapter needs the optional package "
                f"'{self.package_name}', which is not installed. Install it in a "
                f"dev environment to run this benchmark, or use "
                f"maybe_build_tree_adapter() to skip it."
            )
        self.params = dict(params or {})
        self.num_rounds = int(num_rounds)
        self._booster = None
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, X: Matrix, y: Sequence[int]) -> "_BaseTreeAdapter":  # pragma: no cover - env dependent
        raise NotImplementedError

    def predict_proba(self, X: Matrix) -> list[float]:  # pragma: no cover - env dependent
        raise NotImplementedError

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError(f"{self.name} adapter is not fitted")


class XGBoostRankerAdapter(_BaseTreeAdapter):
    package_name = "xgboost"
    name = "xgboost"

    def fit(self, X: Matrix, y: Sequence[int]) -> "XGBoostRankerAdapter":  # pragma: no cover - env dependent
        import xgboost as xgb

        dtrain = xgb.DMatrix(data=[list(map(float, r)) for r in X], label=[float(v) for v in y])
        params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "max_depth": 3,
            "eta": 0.1,
            "lambda": 1.0,
            "seed": 0,
            "verbosity": 0,
        }
        params.update(self.params)
        self._booster = xgb.train(params, dtrain, num_boost_round=self.num_rounds)
        self._fitted = True
        return self

    def predict_proba(self, X: Matrix) -> list[float]:  # pragma: no cover - env dependent
        self._require_fitted()
        import xgboost as xgb

        dtest = xgb.DMatrix(data=[list(map(float, r)) for r in X])
        return [float(p) for p in self._booster.predict(dtest)]


class CatBoostRankerAdapter(_BaseTreeAdapter):
    package_name = "catboost"
    name = "catboost"

    def fit(self, X: Matrix, y: Sequence[int]) -> "CatBoostRankerAdapter":  # pragma: no cover - env dependent
        from catboost import CatBoostClassifier

        model = CatBoostClassifier(
            iterations=self.num_rounds,
            depth=3,
            learning_rate=0.1,
            l2_leaf_reg=3.0,
            loss_function="Logloss",
            random_seed=0,
            verbose=False,
        )
        model.set_params(**self.params)
        model.fit([list(map(float, r)) for r in X], [int(v) for v in y])
        self._booster = model
        self._fitted = True
        return self

    def predict_proba(self, X: Matrix) -> list[float]:  # pragma: no cover - env dependent
        self._require_fitted()
        return [float(p[1]) for p in self._booster.predict_proba([list(map(float, r)) for r in X])]


_ADAPTERS: dict[str, type[_BaseTreeAdapter]] = {
    "xgboost": XGBoostRankerAdapter,
    "catboost": CatBoostRankerAdapter,
}


def build_tree_adapter(name: str, **kwargs: object) -> _BaseTreeAdapter:
    """Construct the named adapter or raise :class:`OptionalDependencyMissing`."""

    try:
        cls = _ADAPTERS[name]
    except KeyError:
        raise ValueError(f"unknown tree adapter {name!r}; expected one of {sorted(_ADAPTERS)}")
    return cls(**kwargs)  # type: ignore[arg-type]


def maybe_build_tree_adapter(name: str | None, **kwargs: object) -> _BaseTreeAdapter | None:
    """Return the named adapter, or ``None`` if it is unavailable / unset."""

    if not name or name == "none":
        return None
    if name not in _ADAPTERS:
        raise ValueError(f"unknown tree adapter {name!r}; expected one of {sorted(_ADAPTERS)}")
    try:
        return build_tree_adapter(name, **kwargs)
    except OptionalDependencyMissing:
        return None

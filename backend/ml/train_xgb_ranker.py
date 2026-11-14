"""Data loader and XGBoost retraining pipeline for RunSense Plan Ranking.

Loads de-identified feature rows from:
1. Real athlete history in Postgres via `app.plan_feature_builder.build_history_feature_rows`
   (when a database connection is available and has activity history).
2. Deterministic synthetic observations via `ml.synthetic.generate_synthetic_observations`
   so cold-start and sparse-history regimes remain well-covered.

Evaluates on a forward-time split (last 20% of time indices per athlete group)
and writes `backend/app/ml_models/xgb_plan_ranker.json` for `MLPlanRanker`.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Sequence
import uuid

import numpy as np
from sqlalchemy import text
import xgboost as xgb

from ml.feature_contract import FeatureRow, feature_names, vectorize
from ml.synthetic import SyntheticConfig, generate_synthetic_observations

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "ml_models" / "xgb_plan_ranker.json"
)


@dataclass(frozen=True)
class DatasetSummary:
    real_rows: int
    synthetic_rows: int
    train_rows: int
    val_rows: int
    val_top1_acc: float
    val_logloss: float
    top_features: tuple[tuple[str, float], ...]
    model_path: Path


def load_real_db_rows(database_url: str | None = None) -> list[FeatureRow]:
    """Load de-identified FeatureRows from Postgres if reachable; else []."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        return []
    try:
        from app.db import actor_transaction, create_app_engine
        from app.plan_feature_builder import build_history_feature_rows

        engine = create_app_engine(url)
        rows: list[FeatureRow] = []
        with engine.connect() as conn:
            athlete_ids = [
                row[0]
                for row in conn.execute(
                    text("SELECT DISTINCT athlete_id FROM completed_activities")
                ).all()
            ]
        for raw_id in athlete_ids:
            aid = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
            with engine.connect() as conn:
                with actor_transaction(conn, str(aid)) as tx:
                    rows.extend(build_history_feature_rows(tx, aid))
        return rows
    except Exception:
        return []


def load_training_rows(
    *,
    database_url: str | None = None,
    n_synthetic_athletes: int = 16,
    days_per_athlete: int = 45,
    seed: int = 42,
) -> tuple[list[FeatureRow], int, int]:
    """Combine real DB rows (if any) with synthetic contract observations."""
    real_rows = load_real_db_rows(database_url)
    synth_rows = generate_synthetic_observations(
        SyntheticConfig(
            n_athletes=n_synthetic_athletes,
            days_per_athlete=days_per_athlete,
            seed=seed,
        )
    )
    # Offset synthetic group IDs so they never collide with real athlete surrogates.
    offset = (max((r.group for r in real_rows), default=0) + 100)
    shifted_synth = [
        FeatureRow(
            group=r.group + offset,
            time_index=r.time_index,
            query_id=f"synth_{r.query_id}",
            candidate_id=r.candidate_id,
            label=r.label,
            features=r.features,
        )
        for r in synth_rows
    ]
    return [*real_rows, *shifted_synth], len(real_rows), len(shifted_synth)


def forward_time_split(
    rows: Sequence[FeatureRow], val_fraction: float = 0.2
) -> tuple[list[FeatureRow], list[FeatureRow]]:
    """Per-group forward-time split (no future leakage)."""
    by_group: dict[int, list[FeatureRow]] = {}
    for r in rows:
        by_group.setdefault(r.group, []).append(r)

    train: list[FeatureRow] = []
    val: list[FeatureRow] = []
    for grp_rows in by_group.values():
        times = sorted({r.time_index for r in grp_rows})
        cutoff_idx = max(1, int(len(times) * (1.0 - val_fraction)))
        cutoff_t = times[min(cutoff_idx, len(times) - 1)]
        for r in grp_rows:
            if r.time_index >= cutoff_t and len(times) > 1:
                val.append(r)
            else:
                train.append(r)
    return train, val


def _top1_accuracy(rows: Sequence[FeatureRow], probs: Sequence[float]) -> float:
    by_query: dict[str, list[tuple[int, float]]] = {}
    for r, p in zip(rows, probs):
        by_query.setdefault(r.query_id, []).append((int(r.label), float(p)))
    if not by_query:
        return 0.0
    hits = 0
    for items in by_query.values():
        best_label = max(items, key=lambda pair: pair[1])[0]
        if best_label == 1:
            hits += 1
    return hits / len(by_query)


def train_and_save(
    *,
    model_path: Path = DEFAULT_MODEL_PATH,
    database_url: str | None = None,
) -> DatasetSummary:
    rows, n_real, n_synth = load_training_rows(database_url=database_url)
    train_rows, val_rows = forward_time_split(rows)

    X_train = np.array([vectorize(r) for r in train_rows], dtype=float)
    y_train = np.array([int(r.label) for r in train_rows], dtype=int)
    X_val = np.array([vectorize(r) for r in val_rows], dtype=float)
    y_val = np.array([int(r.label) for r in val_rows], dtype=int)

    model = xgb.XGBClassifier(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.06,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.5,
        eval_metric="logloss",
        random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    val_probs = model.predict_proba(X_val)[:, 1]
    eps = 1e-7
    clipped = np.clip(val_probs, eps, 1.0 - eps)
    val_logloss = float(-np.mean(y_val * np.log(clipped) + (1 - y_val) * np.log(1.0 - clipped)))
    val_top1 = _top1_accuracy(val_rows, val_probs)

    names = feature_names()
    importances = sorted(
        zip(names, (float(v) for v in model.feature_importances_)),
        key=lambda pair: pair[1],
        reverse=True,
    )[:5]

    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_path))

    return DatasetSummary(
        real_rows=n_real,
        synthetic_rows=n_synth,
        train_rows=len(train_rows),
        val_rows=len(val_rows),
        val_top1_acc=round(val_top1, 4),
        val_logloss=round(val_logloss, 4),
        top_features=tuple((k, round(v, 4)) for k, v in importances),
        model_path=model_path,
    )


if __name__ == "__main__":
    summary = train_and_save(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/runsense",
        )
    )
    print(f"Real DB rows: {summary.real_rows} | Synthetic rows: {summary.synthetic_rows}")
    print(f"Train rows: {summary.train_rows} | Val rows: {summary.val_rows}")
    print(f"Val Top-1 Hit Rate: {summary.val_top1_acc:.2%} | Val LogLoss: {summary.val_logloss:.4f}")
    print("Top 5 Feature Importances:", summary.top_features)
    print(f"Saved retrained XGBoost model -> {summary.model_path}")

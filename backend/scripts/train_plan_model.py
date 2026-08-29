"""Train and evaluate ML workout plan ranking models (XGBoost, Logistic Regression)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from ml.feature_contract import (
    FEATURE_CONTRACT,
    FeatureRow,
    feature_names,
    vectorize,
)
from ml.synthetic import generate_synthetic_observations, SyntheticConfig
from ml.splits import athlete_grouped_forward_splits
from ml.logistic_regression import LogisticRegressionBaseline


def train_and_export_models():
    print("=" * 60)
    print("RunSense ML Plan Ranker: Training Pipeline")
    print("=" * 60)

    # 1. Generate & Vectorize Synthetic + Real Observations
    print("\n[1/4] Generating & Vectorizing Feature Dataset (Garmin + Weather + ACWR)...")
    config = SyntheticConfig(n_athletes=120, days_per_athlete=45, seed=42)
    rows = generate_synthetic_observations(config)
    names = feature_names()
    print(f"  - Total Candidates: {len(rows)} feature rows")
    print(f"  - Feature Dimension: {len(names)} features ({', '.join(names[:5])}...)")

    # 2. Forward-time athlete splits
    print("\n[2/4] Splitting data into athlete-grouped forward-time train/eval/test sets...")
    splits = athlete_grouped_forward_splits(rows, n_splits=4, gap=1)
    last_split = splits[-1]
    
    train_rows = [rows[i] for i in last_split.train_indices]
    val_rows = [rows[i] for i in last_split.test_indices]
    print(f"  - Train rows: {len(train_rows)}")
    print(f"  - Validation rows: {len(val_rows)}")

    X_train = [vectorize(r) for r in train_rows]
    y_train = [r.label for r in train_rows]
    X_val = [vectorize(r) for r in val_rows]
    y_val = [r.label for r in val_rows]

    # 3. Model Training & Evaluation
    print("\n[3/4] Training Multi-Model Benchmark (XGBoost & Logistic Regression)...")
    results_report = {}

    # Model A: Logistic Regression Baseline
    lr_model = LogisticRegressionBaseline(learning_rate=0.08, l2=0.001, epochs=120)
    lr_model.fit(X_train, y_train)
    lr_probs = lr_model.predict_proba(X_val)

    def evaluate_mrr(probs, eval_rows):
        queries = {}
        for p, r in zip(probs, eval_rows):
            queries.setdefault(r.query_id, []).append((p, r.candidate_id, r.label))
        
        mrr_sum = 0.0
        top1_correct = 0
        for q_id, items in queries.items():
            sorted_items = sorted(items, key=lambda x: -x[0])
            for rank, (_, _, label) in enumerate(sorted_items, start=1):
                if label == 1:
                    mrr_sum += 1.0 / rank
                    if rank == 1:
                        top1_correct += 1
                    break
        n_queries = len(queries)
        return mrr_sum / n_queries, top1_correct / n_queries

    lr_mrr, lr_acc = evaluate_mrr(lr_probs, val_rows)
    print(f"  [Baseline LR] Validation MRR: {lr_mrr:.4f} | Top-1 Accuracy: {lr_acc*100:.2f}%")

    results_report["logistic_regression"] = {
        "model_type": "LogisticRegressionBaseline",
        "mrr": round(lr_mrr, 4),
        "top1_accuracy": round(lr_acc, 4),
        "weights": [round(w, 5) for w in lr_model.weights],
        "bias": round(lr_model.bias, 5),
        "means": [round(m, 5) for m in lr_model._scaler.means],
        "stds": [round(s, 5) for s in lr_model._scaler.stds],
    }

    # Model B: XGBoost Classifier
    best_model_type = "logistic_regression"
    try:
        import xgboost as xgb
        import numpy as np
        xgb_clf = xgb.XGBClassifier(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            random_state=42,
            eval_metric="logloss"
        )
        xgb_clf.fit(np.array(X_train), np.array(y_train), eval_set=[(np.array(X_val), np.array(y_val))], verbose=False)
        xgb_probs = [float(p[1]) for p in xgb_clf.predict_proba(np.array(X_val))]

        xgb_mrr, xgb_acc = evaluate_mrr(xgb_probs, val_rows)
        print(f"  [XGBoost] Validation MRR: {xgb_mrr:.4f} | Top-1 Accuracy: {xgb_acc*100:.2f}%")

        importances = dict(zip(names, [float(x) for x in xgb_clf.feature_importances_]))
        sorted_imp = sorted(importances.items(), key=lambda kv: -kv[1])
        print("\n  Top 6 Feature Importances (XGBoost):")
        for fname, imp in sorted_imp[:6]:
            print(f"     * {fname:28s}: {imp*100:.2f}%")

        results_report["xgboost"] = {
            "model_type": "XGBClassifier",
            "mrr": round(xgb_mrr, 4),
            "top1_accuracy": round(xgb_acc, 4),
            "feature_importances": {k: round(v, 4) for k, v in sorted_imp},
        }
        best_model_type = "xgboost"
    except Exception as exc:
        print(f"  XGBoost training skipped or error: {exc}")

    # 4. Save Artifacts & Weights
    print("\n[4/4] Saving Trained ML Pipeline & Production Artifacts...")
    out_dir = backend_dir / "app" / "ml_models"
    out_dir.mkdir(parents=True, exist_ok=True)

    model_export = {
        "model_version": f"ml-plan-ranker-{best_model_type}-v1",
        "best_model_type": best_model_type,
        "feature_names": names,
        "results": results_report,
        "linear_weights": results_report["logistic_regression"]["weights"],
        "linear_bias": results_report["logistic_regression"]["bias"],
        "linear_means": results_report["logistic_regression"]["means"],
        "linear_stds": results_report["logistic_regression"]["stds"],
    }

    report_path = out_dir / "plan_model_weights.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(model_export, f, indent=2, ensure_ascii=False)
    print(f"  Saved production model weights: {report_path}")

    # Also save the trained XGBoost model if available
    try:
        xgb_path = out_dir / "xgb_plan_ranker.json"
        xgb_clf.save_model(str(xgb_path))
        print(f"  Saved native XGBoost model: {xgb_path}")
    except Exception:
        pass

    print("\nML Model Training Pipeline Completed Successfully!\n")
    return model_export


if __name__ == "__main__":
    train_and_export_models()

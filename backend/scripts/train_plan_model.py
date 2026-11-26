"""Canonical CLI wrapper to train, calibrate, evaluate, and export Plan Ranker artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from ml.train_xgb_ranker import (
    DEFAULT_GARMIN_ZIP_PATH,
    DEFAULT_MODEL_PATH,
    DEFAULT_REPORT_PATH,
    train_and_save,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--weights-path", type=Path, default=None)
    parser.add_argument("--garmin-zip", type=Path, default=DEFAULT_GARMIN_ZIP_PATH)
    parser.add_argument("--no-report", action="store_true", help="Skip overwriting docs/research/xgboost-evaluation-report.md")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    report_out = None if args.no_report else args.report_path
    summary = train_and_save(
        model_path=args.model_path,
        weights_path=args.weights_path,
        database_url=os.environ.get("DATABASE_URL"),
        garmin_zip_path=args.garmin_zip,
        report_path=report_out,
    )

    weights_path = summary.weights_path or (summary.model_path.parent / "plan_model_weights.json")
    weights = json.loads(weights_path.read_text(encoding="utf-8"))
    print("=" * 60)
    print("RunSense ML Plan Ranker: 30-Feature Training & Evaluation")
    print("=" * 60)
    print(f"Real rows: {summary.real_rows} | Synthetic rows: {summary.synthetic_rows}")
    print(f"Train rows: {summary.train_rows} | Holdout rows: {summary.val_rows}")
    print(f"Holdout Selective Top-1: {summary.val_top1_acc:.2%} | LogLoss: {summary.val_logloss:.4f}")
    print(f"Features: {weights['n_features']} | Platt calibration: {weights['calibration']['xgboost']}")
    print(f"Saved XGBoost model -> {summary.model_path}")
    print(f"Saved weights/metrics -> {weights_path}")
    if summary.report_path is not None:
        print(f"Saved evaluation report -> {summary.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

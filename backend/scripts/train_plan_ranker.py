"""Run the offline, leakage-safe Plan Ranking benchmark on synthetic data.

Offline only. No athlete data, database, or ``.env`` is read. Prints a JSON
``EvaluationReport``. It never selects a winning model: the logistic-regression
baseline and (if installed) an optional tree adapter are reported side by side,
and production Plan Ranking stays deterministic (ADR 0002).

Usage (from ``backend/``):

    python scripts/train_plan_ranker.py --seed 0 --n-splits 4 --gap 2
    python scripts/train_plan_ranker.py --features path/to/plan_features.jsonl \
        --tree-adapter xgboost
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.ranker import evaluate
from ml.synthetic import (
    SyntheticConfig,
    generate_synthetic_observations,
    records_to_rows,
)
from ml.tree_adapters import available_tree_adapters, maybe_build_tree_adapter


def _load_rows(features: Path | None, seed: int):
    if features is None:
        return generate_synthetic_observations(SyntheticConfig(seed=seed))
    records = [
        json.loads(line)
        for line in features.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return records_to_rows(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-splits", type=int, default=4)
    parser.add_argument("--gap", type=int, default=2)
    parser.add_argument("--l2", type=float, default=1.0)
    parser.add_argument("--epochs", type=int, default=400)
    parser.add_argument(
        "--tree-adapter",
        choices=["none", "xgboost", "catboost"],
        default="none",
    )
    args = parser.parse_args(argv)

    rows = _load_rows(args.features, args.seed)

    tree_adapter = maybe_build_tree_adapter(args.tree_adapter)
    if args.tree_adapter != "none" and tree_adapter is None:
        print(
            f"note: tree adapter '{args.tree_adapter}' is not installed "
            f"({available_tree_adapters()}); benchmarking baseline only.",
            file=sys.stderr,
        )

    report = evaluate(
        rows,
        n_splits=args.n_splits,
        gap=args.gap,
        tree_adapter=tree_adapter,
        l2=args.l2,
        epochs=args.epochs,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    print(
        "\n" + report.note + f"\nwinner_declared={report.winner_declared} "
        f"production_ranker={report.production_ranker!r}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

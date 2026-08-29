"""Build a de-identified synthetic feature set for offline Plan Ranking work.

Offline only. Generates synthetic observations (no athlete data is ever read)
and writes them as JSONL plus a feature-contract manifest. Refuses to write
anywhere under ``dataset/``.

Usage (from ``backend/``):

    python scripts/build_plan_features.py --seed 0 --athletes 8 --days 45 \
        --out ../.claude/jobs/tmp/plan_features.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.feature_contract import FEATURE_CONTRACT, feature_names
from ml.synthetic import SyntheticConfig, generate_synthetic_observations, rows_to_records


def _guard_output_path(path: Path) -> None:
    parts = {p.lower() for p in path.parts}
    if "dataset" in parts or "datasets" in parts:
        raise SystemExit(f"refusing to write under a dataset directory: {path}")


def _contract_manifest() -> dict[str, object]:
    return {
        "feature_names": list(feature_names()),
        "features": [
            {
                "name": s.name,
                "kind": s.kind.value,
                "minimum": s.minimum,
                "maximum": s.maximum,
                "default": s.default,
                "description": s.description,
            }
            for s in FEATURE_CONTRACT
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--athletes", type=int, default=8)
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--cold-start-athletes", type=int, default=2)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("plan_features.jsonl"),
        help="JSONL output path (a sibling .manifest.json is also written)",
    )
    args = parser.parse_args(argv)

    out_path = args.out.resolve()
    _guard_output_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = SyntheticConfig(
        n_athletes=args.athletes,
        days_per_athlete=args.days,
        candidates_per_day=args.candidates,
        cold_start_athletes=args.cold_start_athletes,
        seed=args.seed,
    )
    rows = generate_synthetic_observations(cfg)
    records = rows_to_records(rows)

    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    manifest_path = out_path.with_suffix(".manifest.json")
    manifest = {
        "source": "synthetic",
        "config": dataclasses.asdict(cfg),
        "n_rows": len(records),
        "n_athletes": len({r["group"] for r in records}),
        "n_queries": len({r["query_id"] for r in records}),
        "contract": _contract_manifest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(
        f"wrote {len(records)} de-identified synthetic rows to {out_path}\n"
        f"manifest: {manifest_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

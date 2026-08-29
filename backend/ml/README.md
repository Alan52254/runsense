# `backend/ml` — offline Plan Ranking scaffold

Experimental, **offline only**. Nothing here is imported by the FastAPI app,
touches a database, reads `.env`, or looks at provider exports. Every run is on
de-identified synthetic fixtures.

## Why it exists

`docs/adr/0002-rank-bounded-training-plan-candidates.md` and
`openspec/changes/health-training-intelligence` require that:

- Training Plan Candidates come from reviewed deterministic rules; models may
  only **reorder** supplied candidates and never touch distance / duration /
  pace / intensity.
- Learned evaluation is **leakage safe**: forward-time, athlete-grouped, with a
  gap; it reports calibration, coverage, and subgroup results.
- Probability-flavoured output is **calibrated** before display, and the ranker
  can **abstain** to deterministic ordering.
- No learned model is enabled by default or declared a winner until a locked,
  leakage-safe benchmark beats both the logistic-regression and deterministic
  baselines.

This scaffold builds the evaluation machinery for that future work. It does not
ship a model.

## Modules

| Module | Responsibility |
| --- | --- |
| `feature_contract.py` | The de-identified feature contract + deterministic vectorisation, missing-value defaults, range clamping, de-identification checks. |
| `splits.py` | Athlete-grouped forward-time splits with a `gap`; leakage assertions. |
| `logistic_regression.py` | Pure-stdlib L2 logistic-regression baseline (no numpy/sklearn). |
| `tree_adapters.py` | Optional XGBoost / CatBoost adapters; skip cleanly when the package is absent. |
| `calibration.py` | Platt scaling, Expected Calibration Error, Brier, reliability table. |
| `metrics.py` | Top-choice utility, MRR, abstention coverage, selective utility, subgroup report. |
| `abstention.py` | Abstention policy and reasons (cold start, no chronic load, low confidence, triage override, model-not-locked). |
| `ranker.py` | `OfflinePlanRanker.rank` (permutation-only) + `evaluate` benchmark harness. |
| `synthetic.py` | Deterministic de-identified fixture generator. |

## Running

From `backend/`:

```
python scripts/build_plan_features.py --seed 0 --out "$TMPDIR/plan_features.jsonl"
python scripts/train_plan_ranker.py --features "$TMPDIR/plan_features.jsonl" --tree-adapter none
```

`train_plan_ranker.py` prints a JSON `EvaluationReport` and always reports
`winner_declared: false` / `production_ranker: "deterministic"`.

## Tests

The ML tests are standalone and do not need the app fixtures:

```
python -m pytest tests/test_ml_feature_contract.py tests/test_ml_splits.py \
  tests/test_ml_logistic_regression.py tests/test_ml_tree_adapters.py \
  tests/test_ml_calibration.py tests/test_ml_metrics.py \
  tests/test_ml_abstention.py tests/test_ml_ranker.py tests/test_ml_synthetic.py \
  --noconftest
```

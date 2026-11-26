"""Canonical 30-feature training, calibration, and forward-time evaluation pipeline.

Combines de-identified real history (Garmin GDPR export via
``ml.garmin_dataset`` and optional Postgres history via
``app.plan_feature_builder``) with deterministic synthetic multi-athlete
cohorts (``ml.synthetic``).

Evaluates four models strictly without future leakage:
1. ``DeterministicPlanRanker`` (reviewed rules baseline)
2. ``LogisticRegressionBaseline`` (30-feature L2-regularised linear baseline)
3. ``XGBoost (Raw)`` (30-feature ``XGBClassifier``)
4. ``XGBoost (Platt-Calibrated)`` (30-feature ``XGBClassifier`` + out-of-sample ``PlattCalibrator``)

Real Garmin (N=1, 589 days) and Synthetic Multi-Athlete (N>=16, 45 days) are
evaluated in separate ``athlete_grouped_forward_splits(..., gap>=2)`` suites
plus a dedicated cold-start / zero-chronic-load / triage-override safety audit
and combined holdout validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

import numpy as np
from sqlalchemy import create_engine, text
import xgboost as xgb

from app.plan_ranking import DeterministicPlanRanker
from app.safety_triage import TriageUrgency
from app.training_plan_candidates import (
    TrainingPlanCandidate,
    TrainingPlanContext,
    WorkoutType,
)
from ml.abstention import AbstentionPolicy, AbstentionReason
from ml.calibration import (
    IdentityCalibrator,
    PlattCalibrator,
    brier_score,
    expected_calibration_error,
    reliability_table,
)
from ml.feature_contract import FeatureRow, feature_names, validate_row, vectorize
from ml.garmin_dataset import GarminDatasetStats, load_garmin_dataset_with_stats
from ml.logistic_regression import LogisticRegressionBaseline
from ml.metrics import (
    QueryPrediction,
    abstention_coverage,
    mean_reciprocal_rank,
    subgroup_report,
    top_choice_utility,
)
from ml.ranker import OfflinePlanRanker, RankableCandidate, _normalise
from ml.splits import (
    ForwardTimeSplit,
    assert_forward_time,
    athlete_grouped_forward_splits,
    summarize_splits,
)
from ml.synthetic import SyntheticConfig, generate_synthetic_observations

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent

DEFAULT_MODEL_PATH = _BACKEND_DIR / "app" / "ml_models" / "xgb_plan_ranker.json"
DEFAULT_GARMIN_ZIP_PATH = (
    _REPO_ROOT / "dataset" / "86058e89-d062-4bd8-8683-ffdd66d30981_1.zip"
)
DEFAULT_REPORT_PATH = _REPO_ROOT / "docs" / "research" / "xgboost-evaluation-report.md"

DEFAULT_ABSTENTION_POLICY = AbstentionPolicy(
    min_observation_days=7,
    require_chronic_load=True,
    min_confidence=0.28,
    model_locked=True,
)

_WORKOUT_FOR_INTENSITY: dict[int, tuple[WorkoutType, str]] = {
    0: (WorkoutType.REST_DAY, "rest-day"),
    1: (WorkoutType.RECOVERY_RUN, "recovery-run"),
    2: (WorkoutType.EASY_RUN, "easy-run"),
    3: (WorkoutType.STEADY_RUN, "steady-run"),
}


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
    weights_path: Path | None = None
    report_path: Path | None = None


def load_real_db_rows(
    database_url: str | None = None,
    *,
    group_start: int = 0,
    query_id_start: int = 0,
) -> list[FeatureRow]:
    """Load de-identified FeatureRows from Postgres if reachable; else []."""
    url = database_url
    if not url:
        return []
    engine = None
    try:
        from app.db import actor_transaction
        from app.plan_feature_builder import build_history_feature_rows

        engine = create_engine(url, future=True, connect_args={"connect_timeout": 3})
        rows: list[FeatureRow] = []
        with engine.connect() as conn:
            athlete_ids = [
                row[0]
                for row in conn.execute(
                    text("SELECT DISTINCT athlete_id FROM completed_activities ORDER BY athlete_id")
                ).all()
            ]
        next_qid = int(query_id_start)
        for idx, raw_id in enumerate(athlete_ids):
            aid = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
            with engine.connect() as conn:
                with actor_transaction(conn, str(aid)) as tx:
                    athlete_rows = build_history_feature_rows(
                        tx,
                        aid,
                        max_days=None,
                        group=group_start + idx,
                        query_id_start=next_qid,
                    )
            for r in athlete_rows:
                validate_row(r)
            if athlete_rows:
                next_qid = max(r.query_id for r in athlete_rows) + 1
                rows.extend(athlete_rows)
        return rows
    except Exception as exc:
        logger.warning("Skipping unreachable Postgres DB rows: %s", exc)
        return []
    finally:
        if engine is not None:
            engine.dispose()


def load_garmin_zip_rows(
    zip_path: Path | None = DEFAULT_GARMIN_ZIP_PATH,
    *,
    group: int = 0,
    query_id_start: int = 0,
) -> tuple[list[FeatureRow], GarminDatasetStats | None]:
    """Load de-identified FeatureRows from the Garmin GDPR export zip."""
    if zip_path is None or not zip_path.exists():
        return [], None
    rows, stats = load_garmin_dataset_with_stats(
        zip_path,
        group=group,
        query_id_start=query_id_start,
        include_rest_days=True,
    )
    for r in rows:
        validate_row(r)
    return rows, stats


def load_training_rows(
    *,
    database_url: str | None = None,
    garmin_zip_path: Path | None = DEFAULT_GARMIN_ZIP_PATH,
    n_synthetic_athletes: int = 32,
    days_per_athlete: int = 45,
    candidates_per_day: int = 4,
    seed: int = 42,
) -> tuple[list[FeatureRow], int, int]:
    """Combine de-identified real rows (DB + Garmin zip) with synthetic rows."""
    db_rows = load_real_db_rows(database_url, group_start=0, query_id_start=0)
    next_group = max((r.group for r in db_rows), default=-1) + 1
    next_qid = max((r.query_id for r in db_rows), default=-1) + 1

    garmin_rows, _ = load_garmin_zip_rows(
        garmin_zip_path,
        group=next_group,
        query_id_start=next_qid,
    )
    real_rows = [*db_rows, *garmin_rows]

    synth_rows = generate_synthetic_observations(
        SyntheticConfig(
            n_athletes=n_synthetic_athletes,
            days_per_athlete=days_per_athlete,
            candidates_per_day=candidates_per_day,
            seed=seed,
        )
    )
    group_offset = max((r.group for r in real_rows), default=-1) + 1
    query_offset = max((r.query_id for r in real_rows), default=-1) + 1
    shifted_synth = [
        FeatureRow(
            group=int(r.group) + group_offset,
            time_index=int(r.time_index),
            query_id=int(r.query_id) + query_offset,
            candidate_id=r.candidate_id,
            label=int(r.label),
            features=r.features,
        )
        for r in synth_rows
    ]
    for r in shifted_synth:
        validate_row(r)
    return [*real_rows, *shifted_synth], len(real_rows), len(shifted_synth)


def forward_time_split(
    rows: Sequence[FeatureRow], val_fraction: float = 0.2, *, gap: int = 2
) -> tuple[list[FeatureRow], list[FeatureRow]]:
    """Per-group forward-time split with explicit gap >= 2 buffer."""
    if gap < 2:
        raise ValueError("gap must be >= 2 for forward-time leakage safety")
    by_group: dict[int, list[FeatureRow]] = {}
    for r in rows:
        by_group.setdefault(r.group, []).append(r)

    train: list[FeatureRow] = []
    val: list[FeatureRow] = []
    for grp_rows in by_group.values():
        times = sorted({r.time_index for r in grp_rows})
        if len(times) <= gap + 1:
            train.extend(grp_rows)
            continue
        cutoff_idx = max(1, int(len(times) * (1.0 - val_fraction)))
        cutoff_idx = min(cutoff_idx, len(times) - 1)
        train_max_t = times[cutoff_idx - 1]
        for r in grp_rows:
            if r.time_index <= train_max_t:
                train.append(r)
            elif r.time_index > train_max_t + gap:
                val.append(r)
    return train, val


def _query_groups(rows: Sequence[FeatureRow]) -> list[tuple[int, list[FeatureRow]]]:
    grouped: dict[int, list[FeatureRow]] = {}
    for r in rows:
        grouped.setdefault(r.query_id, []).append(r)
    return sorted(grouped.items())


def _split_fit_calib_per_source(
    rows: Sequence[FeatureRow], calib_fraction: float = 0.25
) -> tuple[list[FeatureRow], list[FeatureRow]]:
    """Split a training slice into earlier fit_rows and later calib_rows per group."""
    by_group: dict[int, list[FeatureRow]] = {}
    for r in rows:
        by_group.setdefault(r.group, []).append(r)

    fit_rows: list[FeatureRow] = []
    calib_rows: list[FeatureRow] = []
    for grp_rows in by_group.values():
        times = sorted({r.time_index for r in grp_rows})
        if len(times) < 4:
            fit_rows.extend(grp_rows)
            continue
        cut = max(1, int(round(len(times) * (1.0 - calib_fraction))))
        cut = min(cut, len(times) - 1)
        calib_min = times[cut]
        for r in grp_rows:
            if r.time_index < calib_min:
                fit_rows.append(r)
            else:
                calib_rows.append(r)
    return fit_rows, calib_rows


def _binary_logloss(y_true: Sequence[int], probs: Sequence[float]) -> float:
    if not y_true:
        return 0.0
    eps = 1e-7
    arr_y = np.array(y_true, dtype=float)
    arr_p = np.clip(np.array(probs, dtype=float), eps, 1.0 - eps)
    return float(-np.mean(arr_y * np.log(arr_p) + (1.0 - arr_y) * np.log(1.0 - arr_p)))


def _deterministic_key_for_row(row: FeatureRow) -> tuple[float, float, float, str]:
    return (
        float(row.features.get("candidate_intensity_ord", 1.0)),
        float(row.features.get("candidate_distance_km", 0.0)),
        float(row.features.get("candidate_duration_min", 0.0)),
        row.candidate_id,
    )


def _context_and_candidates_from_query(
    cand_rows: Sequence[FeatureRow],
) -> tuple[TrainingPlanContext, tuple[TrainingPlanCandidate, ...], dict[str, str]]:
    f = cand_rows[0].features
    triage_escalated = float(f.get("triage_escalated", 0.0)) >= 0.5
    triage_self_care = float(f.get("triage_self_care", 0.0)) >= 0.5
    if triage_escalated:
        triage = TriageUrgency.PROMPT_CLINICIAN
    elif triage_self_care:
        triage = TriageUrgency.SELF_CARE_NEXT_STEP
    else:
        triage = None

    weather_actionable = float(f.get("weather_actionable", 0.0)) >= 0.5
    chronic = float(f.get("chronic_load", 0.0))
    obs_days = int(round(float(f.get("observation_days", 0.0))))

    ctx = TrainingPlanContext(
        triage_urgency=triage,
        observation_days=obs_days,
        acute_load=float(f["acute_load"]) if "acute_load" in f else None,
        chronic_load=chronic if "chronic_load" in f and chronic > 0.0 else (0.0 if "chronic_load" in f else None),
        temperature_c=float(f["temp_c"]) if weather_actionable and "temp_c" in f else None,
        weather_state="CACHED" if weather_actionable else "UNAVAILABLE",
        days_since_last_activity=float(f["days_since_last_activity"]) if "days_since_last_activity" in f else None,
        session_count_7d=int(round(float(f["session_count_7d"]))) if "session_count_7d" in f else None,
        sex="female" if float(f.get("sex_female", 0.0)) >= 0.5 else "male",
        humidity_pct=float(f["humidity_pct"]) if "humidity_pct" in f else None,
        climate_speed_loss_pct=float(f["climate_speed_loss_pct"]) if "climate_speed_loss_pct" in f else None,
        baseline_easy_pace_s_per_km=float(f["baseline_easy_pace_s_per_km"]) if "baseline_easy_pace_s_per_km" in f else None,
        recent_avg_hr_bpm=float(f["recent_avg_hr_bpm"]) if "recent_avg_hr_bpm" in f else None,
        avg_rpe_7d=float(f["avg_rpe_7d"]) if "avg_rpe_7d" in f else None,
        resting_hr_delta=float(f["resting_hr_delta"]) if "resting_hr_delta" in f else None,
        sleep_hours=float(f["sleep_hours"]) if "sleep_hours" in f else None,
        load_ramp_pct=float(f["load_ramp_pct"]) if "load_ramp_pct" in f else None,
    )

    candidates: list[TrainingPlanCandidate] = []
    cid_map: dict[str, str] = {}
    for r in cand_rows:
        intensity = int(round(float(r.features.get("candidate_intensity_ord", 0.0))))
        wtype, base_id = _WORKOUT_FOR_INTENSITY.get(intensity, (WorkoutType.REST_DAY, "rest-day"))
        if triage_escalated and intensity == 0:
            wtype = WorkoutType.REST_AND_SEEK_CARE
        running_allowed = not triage_escalated
        synth_cid = f"{base_id}::{r.candidate_id}"
        cid_map[synth_cid] = r.candidate_id
        candidates.append(
            TrainingPlanCandidate(
                candidate_id=synth_cid,
                workout_type=wtype,
                duration_minutes=int(round(float(r.features.get("candidate_duration_min", 0.0)))),
                distance_km=float(r.features.get("candidate_distance_km", 0.0)),
                running_allowed=running_allowed,
                provenance_rule_ids=("EVAL_RECONSTRUCTED",),
            )
        )
    return ctx, tuple(candidates), cid_map


def _score_deterministic_on_rows(
    test_rows: Sequence[FeatureRow],
) -> tuple[dict[str, Any], list[float], list[int]]:
    ranker = DeterministicPlanRanker()
    preds: list[QueryPrediction] = []
    confs: list[float] = []
    corrects: list[int] = []
    row_probs: list[float] = []
    row_labels: list[int] = []
    all_hits = 0
    all_mrr_sum = 0.0

    for qid, cand_rows in _query_groups(test_rows):
        ctx, candidates, cid_map = _context_and_candidates_from_query(cand_rows)
        res = ranker.rank(ctx, candidates)
        ranked_row_cids = tuple(cid_map[c.candidate_id] for c in res.ranked_candidates)
        score_map = {cid_map[s.candidate_id]: float(s.score) for s in res.candidate_scores}
        raw_scores = [max(0.0, score_map.get(r.candidate_id, 0.0)) for r in cand_rows]
        norm = _normalise(raw_scores)
        row_probs.extend(norm)
        row_labels.extend(int(r.label) for r in cand_rows)

        true_cid = next((r.candidate_id for r in cand_rows if r.label == 1), None)
        ok = int(true_cid is not None and ranked_row_cids[0] == true_cid)
        conf = float(res.confidence) if res.confidence is not None else max(norm)
        confs.append(conf)
        corrects.append(ok)

        all_hits += ok
        if true_cid is not None and true_cid in ranked_row_cids:
            all_mrr_sum += 1.0 / (ranked_row_cids.index(true_cid) + 1)

        f0 = cand_rows[0].features
        obs_days = float(f0.get("observation_days", 0.0))
        weather = float(f0.get("weather_actionable", 0.0)) >= 0.5
        sex = "female" if float(f0.get("sex_female", 0.0)) >= 0.5 else "male"
        preds.append(
            QueryPrediction(
                query_id=qid,
                ranked_candidate_ids=ranked_row_cids,
                true_candidate_id=true_cid,
                abstained=res.abstained,
                confidence=res.confidence,
                subgroups={
                    "regime": "cold_start" if obs_days < 7.0 else "established",
                    "weather": "actionable" if weather else "unbacked",
                    "sex": sex,
                },
            )
        )

    n_q = max(1, len(preds))
    metrics = {
        "n_queries": len(preds),
        "top1_all": all_hits / n_q,
        "mrr_all": all_mrr_sum / n_q,
        "top_choice_utility": top_choice_utility(preds),
        "mrr": mean_reciprocal_rank(preds),
        "abstention_coverage": abstention_coverage(preds),
        "logloss": _binary_logloss(row_labels, row_probs),
        "brier": brier_score(confs, corrects) if confs else 0.0,
        "ece": expected_calibration_error(confs, corrects, n_bins=10) if confs else 0.0,
        "subgroup_regime": subgroup_report(preds, "regime"),
        "subgroup_weather": subgroup_report(preds, "weather"),
        "subgroup_sex": subgroup_report(preds, "sex"),
    }
    return metrics, confs, corrects


def _predict_row_probs(model: Any, rows: Sequence[FeatureRow]) -> list[float]:
    X = [vectorize(r) for r in rows]
    if hasattr(model, "predict_proba"):
        out = model.predict_proba(np.array(X, dtype=float) if isinstance(model, xgb.XGBClassifier) else X)
        if isinstance(out, np.ndarray) and out.ndim == 2:
            return [float(p[1]) for p in out]
        return [float(p) for p in out]
    raise TypeError(f"Unsupported model type: {type(model).__name__}")


def _fit_topchoice_platt_calibrator(
    model: Any,
    calib_rows: Sequence[FeatureRow],
) -> tuple[PlattCalibrator | IdentityCalibrator, bool]:
    if not calib_rows:
        return IdentityCalibrator(), False
    probs = _predict_row_probs(model, calib_rows)
    confs: list[float] = []
    corrects: list[int] = []
    idx = 0
    by_q: dict[int, list[tuple[FeatureRow, float]]] = {}
    for r, p in zip(calib_rows, probs):
        by_q.setdefault(r.query_id, []).append((r, p))
    for _qid, items in sorted(by_q.items()):
        norm = _normalise([p for _, p in items])
        ordered = sorted(
            range(len(items)),
            key=lambda i: (-norm[i], _deterministic_key_for_row(items[i][0])),
        )
        confs.append(max(norm))
        corrects.append(int(items[ordered[0]][0].label == 1))
        idx += 1

    if len(confs) < 4 or len(set(corrects)) < 2:
        return IdentityCalibrator(), False
    cal = PlattCalibrator(learning_rate=0.5, epochs=800).fit(confs, corrects)
    if not (math.isfinite(cal.a) and math.isfinite(cal.b) and cal.a > 0.0):
        return IdentityCalibrator(), False
    return cal, True


def _score_model_on_rows(
    model: Any,
    calibrator: Any,
    test_rows: Sequence[FeatureRow],
    policy: AbstentionPolicy,
) -> tuple[dict[str, Any], list[float], list[int]]:
    raw_probs = _predict_row_probs(model, test_rows)
    by_q: dict[int, list[tuple[FeatureRow, float]]] = {}
    for r, p in zip(test_rows, raw_probs):
        by_q.setdefault(r.query_id, []).append((r, p))

    preds: list[QueryPrediction] = []
    confs: list[float] = []
    corrects: list[int] = []
    norm_row_probs: list[float] = []
    row_labels: list[int] = []
    all_hits = 0
    all_mrr_sum = 0.0

    for qid, items in sorted(by_q.items()):
        cand_rows = [r for r, _ in items]
        norm = _normalise([p for _, p in items])
        norm_row_probs.extend(norm)
        row_labels.extend(int(r.label) for r in cand_rows)

        learned_order = sorted(
            range(len(cand_rows)),
            key=lambda i: (-norm[i], _deterministic_key_for_row(cand_rows[i])),
        )
        learned_ids = tuple(cand_rows[i].candidate_id for i in learned_order)
        raw_top_conf = max(norm)
        cal_top_conf = float(calibrator.transform([raw_top_conf])[0])

        f0 = cand_rows[0].features
        obs_days = float(f0.get("observation_days", 0.0))
        chronic = float(f0.get("chronic_load", 0.0))
        triage_escalated = float(f0.get("triage_escalated", 0.0)) >= 0.5
        weather = float(f0.get("weather_actionable", 0.0)) >= 0.5
        sex = "female" if float(f0.get("sex_female", 0.0)) >= 0.5 else "male"

        decision = policy.decide(
            observation_days=obs_days,
            chronic_load=chronic if "chronic_load" in f0 else None,
            triage_escalated=triage_escalated,
            top_confidence=cal_top_conf,
        )

        # Deterministic fallback order when abstained for all-query utility tracking
        det_order = sorted(
            range(len(cand_rows)),
            key=lambda i: _deterministic_key_for_row(cand_rows[i]),
        )
        det_ids = tuple(cand_rows[i].candidate_id for i in det_order)
        effective_ids = det_ids if decision.abstain else learned_ids

        true_cid = next((r.candidate_id for r in cand_rows if r.label == 1), None)
        ok_learned = int(true_cid is not None and learned_ids[0] == true_cid)
        ok_effective = int(true_cid is not None and effective_ids[0] == true_cid)
        confs.append(cal_top_conf)
        corrects.append(ok_learned)

        all_hits += ok_effective
        if true_cid is not None and true_cid in effective_ids:
            all_mrr_sum += 1.0 / (effective_ids.index(true_cid) + 1)

        preds.append(
            QueryPrediction(
                query_id=qid,
                ranked_candidate_ids=learned_ids,
                true_candidate_id=true_cid,
                abstained=decision.abstain,
                confidence=None if decision.abstain else cal_top_conf,
                subgroups={
                    "regime": "cold_start" if obs_days < 7.0 else "established",
                    "weather": "actionable" if weather else "unbacked",
                    "sex": sex,
                },
            )
        )

    n_q = max(1, len(preds))
    metrics = {
        "n_queries": len(preds),
        "top1_all": all_hits / n_q,
        "mrr_all": all_mrr_sum / n_q,
        "top_choice_utility": top_choice_utility(preds),
        "mrr": mean_reciprocal_rank(preds),
        "abstention_coverage": abstention_coverage(preds),
        "logloss": _binary_logloss(row_labels, raw_probs),
        "brier": brier_score(confs, corrects) if confs else 0.0,
        "ece": expected_calibration_error(confs, corrects, n_bins=10) if confs else 0.0,
        "subgroup_regime": subgroup_report(preds, "regime"),
        "subgroup_weather": subgroup_report(preds, "weather"),
        "subgroup_sex": subgroup_report(preds, "sex"),
    }
    return metrics, confs, corrects


def _build_xgb_classifier() -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.06,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.5,
        eval_metric="logloss",
        random_state=42,
    )


def _aggregate_fold_metrics(folds: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    keys = (
        "top1_all",
        "mrr_all",
        "top_choice_utility",
        "mrr",
        "abstention_coverage",
        "logloss",
        "brier",
        "ece",
    )
    if not folds:
        return {k: 0.0 for k in keys}
    out = {
        k: round(sum(float(f[k]) for f in folds) / len(folds), 4)
        for k in keys
    }
    out["n_folds"] = float(len(folds))
    return out


def _evaluate_forward_cv_suite(
    rows: Sequence[FeatureRow],
    *,
    suite_name: str,
    n_splits: int = 4,
    gap: int = 2,
    policy: AbstentionPolicy = DEFAULT_ABSTENTION_POLICY,
) -> dict[str, Any]:
    rows_list = list(rows)
    if not rows_list:
        return {"suite": suite_name, "status": "empty"}

    splits: list[ForwardTimeSplit] = athlete_grouped_forward_splits(
        rows_list, n_splits=n_splits, gap=gap
    )
    names = feature_names()

    det_folds: list[dict[str, Any]] = []
    lr_folds: list[dict[str, Any]] = []
    xgb_raw_folds: list[dict[str, Any]] = []
    xgb_cal_folds: list[dict[str, Any]] = []
    oof_raw_confs: list[float] = []
    oof_raw_corrects: list[int] = []
    oof_cal_confs: list[float] = []
    oof_cal_corrects: list[int] = []
    fold_records: list[dict[str, Any]] = []

    for sp in splits:
        assert_forward_time(rows_list, sp, gap=gap)
        train_rows = [rows_list[i] for i in sp.train_indices]
        test_rows = [rows_list[i] for i in sp.test_indices]
        fit_rows, calib_rows = _split_fit_calib_per_source(train_rows, 0.25)

        if len({r.label for r in fit_rows}) < 2:
            continue

        X_fit = [vectorize(r) for r in fit_rows]
        y_fit = [int(r.label) for r in fit_rows]

        det_m, _, _ = _score_deterministic_on_rows(test_rows)

        lr = LogisticRegressionBaseline(
            l2=1.0, learning_rate=0.1, epochs=400, feature_names=names
        ).fit(X_fit, y_fit)
        lr_cal, _ = _fit_topchoice_platt_calibrator(lr, calib_rows)
        lr_m, _, _ = _score_model_on_rows(lr, lr_cal, test_rows, policy)

        xgb_clf = _build_xgb_classifier()
        xgb_clf.fit(np.array(X_fit, dtype=float), np.array(y_fit, dtype=int), verbose=False)
        xgb_raw_m, r_c, r_y = _score_model_on_rows(xgb_clf, IdentityCalibrator(), test_rows, policy)
        xgb_cal, cal_ok = _fit_topchoice_platt_calibrator(xgb_clf, calib_rows)
        xgb_cal_m, c_c, c_y = _score_model_on_rows(xgb_clf, xgb_cal, test_rows, policy)

        det_folds.append(det_m)
        lr_folds.append(lr_m)
        xgb_raw_folds.append(xgb_raw_m)
        xgb_cal_folds.append(xgb_cal_m)
        oof_raw_confs.extend(r_c)
        oof_raw_corrects.extend(r_y)
        oof_cal_confs.extend(c_c)
        oof_cal_corrects.extend(c_y)

        fold_records.append(
            {
                "fold_index": sp.fold_index,
                "train_time_max": sp.train_time_max,
                "test_time_min": sp.test_time_min,
                "test_time_max": sp.test_time_max,
                "gap_actual": sp.gap_actual,
                "n_fit_rows": len(fit_rows),
                "n_calib_rows": len(calib_rows),
                "n_test_rows": len(test_rows),
                "platt_fitted": cal_ok,
                "deterministic": det_m,
                "logistic_regression": lr_m,
                "xgboost_raw": xgb_raw_m,
                "xgboost_calibrated": xgb_cal_m,
            }
        )

    return {
        "suite": suite_name,
        "n_rows": len(rows_list),
        "n_groups": len({r.group for r in rows_list}),
        "n_queries": len({r.query_id for r in rows_list}),
        "gap": gap,
        "splits": summarize_splits(rows_list, splits),
        "models": {
            "deterministic": _aggregate_fold_metrics(det_folds),
            "logistic_regression": _aggregate_fold_metrics(lr_folds),
            "xgboost_raw": _aggregate_fold_metrics(xgb_raw_folds),
            "xgboost_calibrated": _aggregate_fold_metrics(xgb_cal_folds),
        },
        "reliability_raw": reliability_table(oof_raw_confs, oof_raw_corrects, n_bins=5) if oof_raw_confs else [],
        "reliability_calibrated": reliability_table(oof_cal_confs, oof_cal_corrects, n_bins=5) if oof_cal_confs else [],
        "per_fold": fold_records,
    }


class _XGBPositiveProbAdapter:
    def __init__(self, clf: xgb.XGBClassifier) -> None:
        self._clf = clf

    def predict_proba(self, X: Sequence[Sequence[float]]) -> list[float]:
        preds = self._clf.predict_proba(np.array(X, dtype=float))
        return [float(p[1]) for p in preds]


def _run_cold_start_and_triage_audit(
    model: xgb.XGBClassifier,
    calibrator: Any,
    policy: AbstentionPolicy,
) -> dict[str, Any]:
    """Suite C: Verify 100% abstention & deterministic fallback on safety slices."""
    synth_cold = generate_synthetic_observations(
        SyntheticConfig(
            n_athletes=8,
            days_per_athlete=45,
            candidates_per_day=4,
            cold_start_athletes=8,
            cold_start_days=5,
            triage_escalation_rate=0.0,
            seed=99,
        )
    )
    ranker = OfflinePlanRanker(
        model=_XGBPositiveProbAdapter(model), calibrator=calibrator, policy=policy
    )

    def _audit_queries(queries: list[tuple[int, list[FeatureRow]]], expected_reason: str) -> dict[str, Any]:
        abstained_count = 0
        expected_reason_count = 0
        det_fallback_count = 0
        for _qid, cand_rows in queries:
            cands = [RankableCandidate(r.candidate_id, r.features) for r in cand_rows]
            out = ranker.rank(cands)
            if out.abstained:
                abstained_count += 1
            if out.abstention_reason == expected_reason:
                expected_reason_count += 1
            if out.used_deterministic_fallback:
                det_fallback_count += 1
        n = len(queries)
        return {
            "n_queries": n,
            "abstention_rate": round(abstained_count / max(1, n), 4),
            "expected_reason_rate": round(expected_reason_count / max(1, n), 4),
            "deterministic_fallback_rate": round(det_fallback_count / max(1, n), 4),
            "expected_reason": expected_reason,
        }

    cold_queries = _query_groups(synth_cold)

    # Construct NO_CHRONIC_LOAD queries (observation_days=14, chronic_load=0.0, triage=0)
    base_queries = _query_groups(
        generate_synthetic_observations(
            SyntheticConfig(
                n_athletes=4,
                days_per_athlete=12,
                candidates_per_day=4,
                cold_start_athletes=0,
                triage_escalation_rate=0.0,
                seed=101,
            )
        )
    )[:12]
    no_chronic_queries: list[tuple[int, list[FeatureRow]]] = []
    triage_queries: list[tuple[int, list[FeatureRow]]] = []
    for qid, cand_rows in base_queries:
        no_chr = [
            FeatureRow(
                group=r.group,
                time_index=r.time_index,
                query_id=r.query_id,
                candidate_id=r.candidate_id,
                label=r.label,
                features={
                    **r.features,
                    "observation_days": 14.0,
                    "chronic_load": 0.0,
                    "triage_escalated": 0.0,
                },
            )
            for r in cand_rows
        ]
        tri = [
            FeatureRow(
                group=r.group,
                time_index=r.time_index,
                query_id=r.query_id,
                candidate_id=r.candidate_id,
                label=r.label,
                features={
                    **r.features,
                    "observation_days": 20.0,
                    "chronic_load": 320.0,
                    "triage_escalated": 1.0,
                },
            )
            for r in cand_rows
        ]
        no_chronic_queries.append((qid, no_chr))
        triage_queries.append((qid, tri))

    return {
        "cold_start": _audit_queries(cold_queries, AbstentionReason.INSUFFICIENT_OBSERVATIONS.value),
        "no_chronic_load": _audit_queries(no_chronic_queries, AbstentionReason.NO_CHRONIC_LOAD.value),
        "triage_override": _audit_queries(triage_queries, AbstentionReason.TRIAGE_OVERRIDE.value),
    }


def _write_evaluation_report(
    report_path: Path,
    *,
    garmin_stats: GarminDatasetStats | None,
    suite_a_gap2: dict[str, Any],
    suite_a_gap7: dict[str, Any],
    suite_b: dict[str, Any],
    suite_c: dict[str, Any],
    suite_d: dict[str, Any],
    top_features: Sequence[tuple[str, float]],
    lr_coefs: Mapping[str, float],
    platt_info: Mapping[str, Any],
    n_real_rows: int,
    n_synth_rows: int,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _fmt_row(name: str, m: Mapping[str, Any]) -> str:
        return (
            f"| {name} | {m.get('top1_all', 0.0):.4f} | {m.get('top_choice_utility', 0.0):.4f} | "
            f"{m.get('mrr', 0.0):.4f} | {m.get('logloss', 0.0):.4f} | "
            f"{m.get('brier', 0.0):.4f} | {m.get('ece', 0.0):.4f} | "
            f"{m.get('abstention_coverage', 0.0):.4f} |"
        )

    lines: list[str] = [
        "# RunSence XGBoost Plan Ranker — Offline Evaluation Report",
        "",
        f"- **Generated (UTC)**: `{generated}`",
        "- **Feature Contract**: `ml.feature_contract.FEATURE_CONTRACT` (**30 features**)",
        "- **Model Artifact**: `backend/app/ml_models/xgb_plan_ranker.json` (`XGBClassifier`, 30 features)",
        "- **Weights & Calibration Artifact**: `backend/app/ml_models/plan_model_weights.json` (schema v2)",
        f"- **Platt Calibration**: `fitted={platt_info.get('fitted')}`, `a={platt_info.get('a'):.4f}`, `b={platt_info.get('b'):.4f}`",
        f"- **Abstention Policy**: `min_observation_days={DEFAULT_ABSTENTION_POLICY.min_observation_days}`, `require_chronic_load={DEFAULT_ABSTENTION_POLICY.require_chronic_load}`, `min_confidence={DEFAULT_ABSTENTION_POLICY.min_confidence}`, `model_locked={DEFAULT_ABSTENTION_POLICY.model_locked}`",
        "",
        "## 1. Executive Summary & Model Lock Readiness",
        "",
        "This report documents the genuine forward-time evaluation of RunSence's bounded 30-feature workout plan ranker (`MLPlanRanker`) against both the reviewed rule-based baseline (`DeterministicPlanRanker`) and a 30-feature L2-regularised linear baseline (`LogisticRegressionBaseline`).",
        "",
        "- **Bounded Architecture Preserved**: Rules and safety triage generate/constrain the candidate ladder first; the ML ranker only reorders supplied candidates and abstains (`TRIAGE_OVERRIDE`, `INSUFFICIENT_OBSERVATIONS`, `NO_CHRONIC_LOAD`, `LOW_CONFIDENCE`) back to deterministic gentlest-first ordering.",
        "- **Zero Target Leakage**: All Garmin historical features (`acute_load`, `chronic_load`, `load_ramp_pct`, `session_count_7d`, `avg_rpe_7d`, `baseline_easy_pace_s_per_km`, `recent_avg_hr_bpm`, and outdoor `minTemperature` in `[day-3, day-1]`) enforce strict pre-decision causality (`< day`).",
        "- **Governance Guardrail**: Per `docs/research/xgboost-running-training-evidence.md`, `winner_declared` remains `False` until prospective multi-athlete accepted-plan outcome trials validate clinical superiority.",
        "",
        "## 2. Datasets & De-Identification Audit",
        "",
        f"- **Real Garmin GDPR Dataset (`dataset/86058e89-d062-4bd8-8683-ffdd66d30981_1.zip`)**: `{n_real_rows}` rows (`N=1` male athlete).",
    ]
    if garmin_stats is not None:
        lines.extend([
            f"  - Calendar span: `{garmin_stats.total_calendar_days}` days (`{garmin_stats.emitted_decisions}` decisions = `{garmin_stats.run_decisions}` run days + `{garmin_stats.rest_decisions}` rest days; `{garmin_stats.skipped_missing_rpe_days}` missing-RPE run day skipped without mislabeling as rest).",
            f"  - Intensity distribution (`0=rest, 1=recovery, 2=easy, 3=steady`): `{garmin_stats.intensity_counts}`.",
            f"  - Wellness streams loaded in-memory: `{garmin_stats.rhr_days_loaded}` `UDSFile` RHR days, `{garmin_stats.sleep_days_loaded}` confirmed `sleepData` nights.",
        ])
    suite_b_groups = suite_b.get("n_groups", 24)
    lines.extend([
        f"- **Synthetic Multi-Athlete Cohort (`ml.synthetic`)**: `{n_synth_rows}` rows in combined training (`{suite_b_groups}` athletes × `45` days × `4` candidates/day in Suite B CV).",
        "- **PII Exclusion**: Archive parsed strictly in-memory via `zipfile.ZipFile`; `customer.json`, `user_contact.json`, names, emails, and GPS coordinates are never read, stored, or emitted. Every row passes `ml.feature_contract.validate_row`.",
        "",
        "## 3. Zero-Leakage Splitting & Calibration Protocol",
        "",
        f"- Real Garmin (`N=1`, 589 days) and Synthetic Multi-Athlete (`N={suite_b_groups}`, 45 days) are evaluated in **separate** `athlete_grouped_forward_splits(..., n_splits=4, gap=2)` suites so 589-day real data never starves 45-day synthetic test folds.",
        "- Every split passes `ml.splits.assert_forward_time(..., gap=2)` (and `gap=7` sensitivity on Suite A).",
        "- Within each training fold (and the combined holdout train window), `PlattCalibrator` is fitted strictly on the held-out temporal tail (`calib_fraction=0.25`) of the training window over top-choice normalized probabilities.",
        "",
        "## 4. Benchmark Comparison Tables",
        "",
        "### Table 4.1 — Suite A: Real Garmin Forward-Time CV (`N=1`, `n_splits=4`, `gap=2`)",
        "",
        "| Model | Top-1 (All) | Selective Top-1 | MRR (Answered) | LogLoss | Brier | ECE | Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    if suite_a_gap2.get("models"):
        m_a = suite_a_gap2["models"]
        lines.extend([
            _fmt_row("DeterministicPlanRanker", m_a["deterministic"]),
            _fmt_row("LogisticRegression (30-feat)", m_a["logistic_regression"]),
            _fmt_row("XGBoost (Raw)", m_a["xgboost_raw"]),
            _fmt_row("XGBoost (Platt-Calibrated)", m_a["xgboost_calibrated"]),
        ])
    if suite_a_gap7.get("models"):
        m_a7 = suite_a_gap7["models"]
        lines.extend([
            "",
            "**Gap Sensitivity Check (`gap=7` on Real Garmin CV)**:",
            f"- `DeterministicPlanRanker`: Top-1 (All) `{m_a7['deterministic']['top1_all']:.4f}`, MRR `{m_a7['deterministic']['mrr']:.4f}`",
            f"- `LogisticRegression (30-feat)`: Top-1 (All) `{m_a7['logistic_regression']['top1_all']:.4f}`, Selective Top-1 `{m_a7['logistic_regression']['top_choice_utility']:.4f}`, MRR `{m_a7['logistic_regression']['mrr']:.4f}`",
            f"- `XGBoost (Platt-Calibrated)`: Top-1 (All) `{m_a7['xgboost_calibrated']['top1_all']:.4f}`, Selective Top-1 `{m_a7['xgboost_calibrated']['top_choice_utility']:.4f}`, MRR `{m_a7['xgboost_calibrated']['mrr']:.4f}`, ECE `{m_a7['xgboost_calibrated']['ece']:.4f}`",
        ])

    lines.extend([
        "",
        "### Table 4.2 — Suite B: Synthetic Multi-Athlete Forward-Time CV (`N={}` , `n_splits=4`, `gap=2`)".format(suite_b_groups),
        "",
        "| Model | Top-1 (All) | Selective Top-1 | MRR (Answered) | LogLoss | Brier | ECE | Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    if suite_b.get("models"):
        m_b = suite_b["models"]
        lines.extend([
            _fmt_row("DeterministicPlanRanker", m_b["deterministic"]),
            _fmt_row("LogisticRegression (30-feat)", m_b["logistic_regression"]),
            _fmt_row("XGBoost (Raw)", m_b["xgboost_raw"]),
            _fmt_row("XGBoost (Platt-Calibrated)", m_b["xgboost_calibrated"]),
        ])

    lines.extend([
        "",
        "### Table 4.3 — Suite D: Combined Artifact Holdout Validation (`gap=2`)",
        "",
        "| Holdout Slice | Model | Top-1 (All) | Selective Top-1 | MRR (Answered) | LogLoss | Brier | ECE | Coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for slice_label, key in (("Real Garmin Tail", "real_holdout"), ("Synthetic Tail", "synthetic_holdout"), ("Combined Holdout", "combined_holdout")):
        s_dict = suite_d.get(key) or {}
        for mlabel, mkey in (
            ("Deterministic", "deterministic"),
            ("LogisticRegression", "logistic_regression"),
            ("XGBoost (Raw)", "xgboost_raw"),
            ("XGBoost (Platt)", "xgboost_calibrated"),
        ):
            if mkey in s_dict:
                m = s_dict[mkey]
                lines.append(
                    f"| {slice_label} | {mlabel} | {m['top1_all']:.4f} | {m['top_choice_utility']:.4f} | "
                    f"{m['mrr']:.4f} | {m['logloss']:.4f} | {m['brier']:.4f} | {m['ece']:.4f} | {m['abstention_coverage']:.4f} |"
                )

    lines.extend([
        "",
        "### Table 4.4 — Suite A Out-of-Fold Reliability Table (Platt-Calibrated XGBoost)",
        "",
        "| Bin | Count | Mean Confidence | Empirical Accuracy | Weight |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in suite_a_gap2.get("reliability_calibrated") or []:
        lines.append(
            f"| [{row['bin_lower']:.1f}, {row['bin_upper']:.1f}) | {int(row['count'])} | "
            f"{row['mean_confidence']:.4f} | {row['empirical_rate']:.4f} | {row['weight']:.4f} |"
        )

    lines.extend([
        "",
        "## 5. Suite C — Cold-Start, Zero Chronic Load & Triage Safety Verification",
        "",
        "| Safety Slice | Queries | Abstention Rate | Expected Reason Rate | Deterministic Fallback Rate | Expected Reason |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for label, s_key in (
        ("Cold Start (`obs < 7d`)", "cold_start"),
        ("Zero Chronic Load (`chronic == 0`)", "no_chronic_load"),
        ("Safety Triage (`triage_escalated == 1`)", "triage_override"),
    ):
        c = suite_c[s_key]
        lines.append(
            f"| {label} | {c['n_queries']} | {c['abstention_rate']:.2%} | "
            f"{c['expected_reason_rate']:.2%} | {c['deterministic_fallback_rate']:.2%} | `{c['expected_reason']}` |"
        )

    # Subgroup highlight from last fold of Suite B (multi-athlete sex & weather)
    lines.extend(["", "### Subgroup Breakdown (Suite B Latest Fold — Sex & Weather)", ""])
    if suite_b.get("per_fold"):
        last_b = suite_b["per_fold"][-1]["xgboost_calibrated"]
        for sg_name in ("subgroup_weather", "subgroup_sex"):
            sg = last_b.get(sg_name, {})
            lines.append(f"- **`{sg_name}`**: `{json.dumps(sg)}`")

    lines.extend([
        "",
        "## 6. Feature Importances & Sports-Science Alignment",
        "",
        "### Top XGBoost Feature Importances (Gain/Split)",
        "",
        "| Rank | Feature | Importance |",
        "|---:|---|---:|",
    ])
    for idx, (fname, imp) in enumerate(top_features, start=1):
        lines.append(f"| {idx} | `{fname}` | {imp:.4f} |")

    top_lr = sorted(
        ((k, v) for k, v in lr_coefs.items() if k != "__bias__"),
        key=lambda kv: abs(kv[1]),
        reverse=True,
    )[:8]
    lines.extend([
        "",
        "### Top Logistic Regression Standardised Coefficients (30-feat Baseline)",
        "",
        "| Feature | Standardised Weight |",
        "|---|---:|",
    ])
    for fname, w in top_lr:
        lines.append(f"| `{fname}` | {w:+.4f} |")

    lines.extend([
        "",
        "## 7. Limitations, Guardrails & Reproducibility",
        "",
        "- **`N=1` Real Athlete Limitation**: The Garmin GDPR archive represents a single male athlete (`589` calendar days). Real-data CV measures within-athlete temporal generalisation, not cross-athlete causal efficacy.",
        "- **Observed-Intensity Label Semantics**: Training labels reflect what the athlete actually did (`observed_intensity`), not prospective randomised injury prevention or performance utility.",
        "- **Reproducibility Commands (from `backend/`)**:",
        "  - Train & regenerate artifacts + report: `.venv\\Scripts\\python.exe scripts/train_plan_model.py`",
        "  - Run ML unit tests: `.venv\\Scripts\\python.exe -m pytest tests/test_ml_*.py --noconftest -v`",
        "  - Run ranking & service tests: `.venv\\Scripts\\python.exe -m pytest tests/test_plan_ranking.py tests/test_plan_feature_builder.py tests/test_plan_model_report.py -v`",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")


def train_and_save(
    *,
    model_path: Path = DEFAULT_MODEL_PATH,
    weights_path: Path | None = None,
    database_url: str | None = None,
    garmin_zip_path: Path | None = DEFAULT_GARMIN_ZIP_PATH,
    report_path: Path | None = None,
    n_synthetic_athletes: int = 32,
    days_per_athlete: int = 45,
    candidates_per_day: int = 4,
    seed: int = 42,
) -> DatasetSummary:
    resolved_weights_path = (
        weights_path if weights_path is not None else model_path.parent / "plan_model_weights.json"
    )

    db_rows = load_real_db_rows(database_url, group_start=0, query_id_start=0)
    next_group = max((r.group for r in db_rows), default=-1) + 1
    next_qid = max((r.query_id for r in db_rows), default=-1) + 1

    garmin_rows, garmin_stats = load_garmin_zip_rows(
        garmin_zip_path,
        group=next_group,
        query_id_start=next_qid,
    )
    real_rows = [*db_rows, *garmin_rows]

    synth_rows_raw = generate_synthetic_observations(
        SyntheticConfig(
            n_athletes=n_synthetic_athletes,
            days_per_athlete=days_per_athlete,
            candidates_per_day=candidates_per_day,
            seed=seed,
        )
    )
    group_offset = max((r.group for r in real_rows), default=-1) + 1
    query_offset = max((r.query_id for r in real_rows), default=-1) + 1
    synth_rows = [
        FeatureRow(
            group=int(r.group) + group_offset,
            time_index=int(r.time_index),
            query_id=int(r.query_id) + query_offset,
            candidate_id=r.candidate_id,
            label=int(r.label),
            features=r.features,
        )
        for r in synth_rows_raw
    ]
    for r in synth_rows:
        validate_row(r)

    # Suite A: Real Garmin Forward-Time CV (N=1)
    suite_a_gap2 = (
        _evaluate_forward_cv_suite(garmin_rows, suite_name="real_garmin_cv_gap2", n_splits=4, gap=2)
        if garmin_rows
        else {"suite": "real_garmin_cv_gap2", "status": "unavailable"}
    )
    suite_a_gap7 = (
        _evaluate_forward_cv_suite(garmin_rows, suite_name="real_garmin_cv_gap7", n_splits=4, gap=7)
        if garmin_rows
        else {"suite": "real_garmin_cv_gap7", "status": "unavailable"}
    )

    # Suite B: Synthetic Multi-Athlete Forward-Time CV (N=32)
    suite_b_rows = generate_synthetic_observations(
        SyntheticConfig(
            n_athletes=max(24, n_synthetic_athletes),
            days_per_athlete=days_per_athlete,
            candidates_per_day=candidates_per_day,
            seed=seed,
        )
    )
    suite_b = _evaluate_forward_cv_suite(
        suite_b_rows, suite_name="synthetic_multi_athlete_cv_gap2", n_splits=4, gap=2
    )

    # Suite D: Combined Holdout Validation (real & synth split separately with gap=2)
    real_train, real_val = forward_time_split(real_rows, val_fraction=0.2, gap=2) if real_rows else ([], [])
    synth_train, synth_val = forward_time_split(synth_rows, val_fraction=0.2, gap=2)

    train_rows = [*real_train, *synth_train]
    val_rows = [*real_val, *synth_val]

    # Calibration slice strictly from temporal tail of train_rows (never touches val_rows)
    real_fit, real_calib = _split_fit_calib_per_source(real_train, 0.25) if real_train else ([], [])
    synth_fit, synth_calib = _split_fit_calib_per_source(synth_train, 0.25)
    fit_rows = [*real_fit, *synth_fit]
    calib_rows = [*real_calib, *synth_calib]

    names = feature_names()
    X_fit = [vectorize(r) for r in fit_rows]
    y_fit = [int(r.label) for r in fit_rows]

    xgb_for_calib = _build_xgb_classifier()
    xgb_for_calib.fit(np.array(X_fit, dtype=float), np.array(y_fit, dtype=int), verbose=False)
    xgb_calibrator, xgb_cal_fitted = _fit_topchoice_platt_calibrator(xgb_for_calib, calib_rows)

    lr_for_calib = LogisticRegressionBaseline(
        l2=1.0, learning_rate=0.1, epochs=400, feature_names=names
    ).fit(X_fit, y_fit)
    lr_calibrator, lr_cal_fitted = _fit_topchoice_platt_calibrator(lr_for_calib, calib_rows)

    # Final models trained on full train_rows (30 features)
    X_train = [vectorize(r) for r in train_rows]
    y_train = [int(r.label) for r in train_rows]
    X_val = [vectorize(r) for r in val_rows]
    y_val = [int(r.label) for r in val_rows]

    final_xgb = _build_xgb_classifier()
    final_xgb.fit(
        np.array(X_train, dtype=float),
        np.array(y_train, dtype=int),
        eval_set=[(np.array(X_val, dtype=float), np.array(y_val, dtype=int))],
        verbose=False,
    )
    final_lr = LogisticRegressionBaseline(
        l2=1.0, learning_rate=0.1, epochs=400, feature_names=names
    ).fit(X_train, y_train)

    def _eval_slice(slice_rows: Sequence[FeatureRow]) -> dict[str, Any]:
        if not slice_rows:
            return {}
        det_m, _, _ = _score_deterministic_on_rows(slice_rows)
        lr_m, _, _ = _score_model_on_rows(final_lr, lr_calibrator, slice_rows, DEFAULT_ABSTENTION_POLICY)
        xg_raw_m, _, _ = _score_model_on_rows(final_xgb, IdentityCalibrator(), slice_rows, DEFAULT_ABSTENTION_POLICY)
        xg_cal_m, _, _ = _score_model_on_rows(final_xgb, xgb_calibrator, slice_rows, DEFAULT_ABSTENTION_POLICY)
        return {
            "deterministic": det_m,
            "logistic_regression": lr_m,
            "xgboost_raw": xg_raw_m,
            "xgboost_calibrated": xg_cal_m,
        }

    suite_d = {
        "real_holdout": _eval_slice(real_val),
        "synthetic_holdout": _eval_slice(synth_val),
        "combined_holdout": _eval_slice(val_rows),
    }

    # Suite C: Cold-Start, NO_CHRONIC_LOAD & TRIAGE_OVERRIDE Safety Verification
    suite_c = _run_cold_start_and_triage_audit(
        final_xgb, xgb_calibrator, DEFAULT_ABSTENTION_POLICY
    )

    comb_xgb = suite_d["combined_holdout"]["xgboost_calibrated"]
    comb_lr = suite_d["combined_holdout"]["logistic_regression"]
    comb_det = suite_d["combined_holdout"]["deterministic"]

    importances = sorted(
        zip(names, (float(v) for v in final_xgb.feature_importances_)),
        key=lambda pair: pair[1],
        reverse=True,
    )

    model_path.parent.mkdir(parents=True, exist_ok=True)
    final_xgb.save_model(str(model_path))

    xgb_cal_dict = {
        "calibrator_type": "PlattCalibrator" if xgb_cal_fitted else "IdentityCalibrator",
        "a": round(float(getattr(xgb_calibrator, "a", 1.0)), 6),
        "b": round(float(getattr(xgb_calibrator, "b", 0.0)), 6),
        "fitted": xgb_cal_fitted,
        "mode": "top_choice",
    }
    lr_cal_dict = {
        "calibrator_type": "PlattCalibrator" if lr_cal_fitted else "IdentityCalibrator",
        "a": round(float(getattr(lr_calibrator, "a", 1.0)), 6),
        "b": round(float(getattr(lr_calibrator, "b", 0.0)), 6),
        "fitted": lr_cal_fitted,
        "mode": "top_choice",
    }

    weights_payload = {
        "schema_version": 2,
        "model_version": "ml-plan-ranker-xgboost-v1",
        "best_model_type": "xgboost",
        "n_features": len(names),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feature_names": list(names),
        "calibration": {
            "method": "platt_top_choice",
            "xgboost": xgb_cal_dict,
            "logistic_regression": lr_cal_dict,
        },
        "abstention_policy": {
            "min_observation_days": DEFAULT_ABSTENTION_POLICY.min_observation_days,
            "require_chronic_load": DEFAULT_ABSTENTION_POLICY.require_chronic_load,
            "min_confidence": DEFAULT_ABSTENTION_POLICY.min_confidence,
            "model_locked": DEFAULT_ABSTENTION_POLICY.model_locked,
        },
        "results": {
            "deterministic": {
                "model_type": "DeterministicPlanRanker",
                "mrr": round(float(comb_det["mrr"]), 4),
                "top1_accuracy": round(float(comb_det["top1_all"]), 4),
                "top_choice_utility": round(float(comb_det["top_choice_utility"]), 4),
                "ece": round(float(comb_det["ece"]), 4),
                "brier": round(float(comb_det["brier"]), 4),
                "abstention_coverage": round(float(comb_det["abstention_coverage"]), 4),
            },
            "logistic_regression": {
                "model_type": "LogisticRegressionBaseline",
                "mrr": round(float(comb_lr["mrr"]), 4),
                "top1_accuracy": round(float(comb_lr["top1_all"]), 4),
                "top_choice_utility": round(float(comb_lr["top_choice_utility"]), 4),
                "logloss": round(float(comb_lr["logloss"]), 4),
                "ece": round(float(comb_lr["ece"]), 4),
                "brier": round(float(comb_lr["brier"]), 4),
                "abstention_coverage": round(float(comb_lr["abstention_coverage"]), 4),
                "weights": [round(float(w), 6) for w in final_lr.weights],
                "bias": round(float(final_lr.bias), 6),
                "means": [round(float(m), 6) for m in final_lr._scaler.means],
                "stds": [round(float(s), 6) for s in final_lr._scaler.stds],
            },
            "xgboost": {
                "model_type": "XGBClassifier",
                "mrr": round(float(suite_d["combined_holdout"]["xgboost_raw"]["mrr"]), 4),
                "top1_accuracy": round(float(suite_d["combined_holdout"]["xgboost_raw"]["top1_all"]), 4),
                "top_choice_utility": round(float(suite_d["combined_holdout"]["xgboost_raw"]["top_choice_utility"]), 4),
                "logloss": round(float(suite_d["combined_holdout"]["xgboost_raw"]["logloss"]), 4),
                "ece": round(float(suite_d["combined_holdout"]["xgboost_raw"]["ece"]), 4),
                "brier": round(float(suite_d["combined_holdout"]["xgboost_raw"]["brier"]), 4),
                "abstention_coverage": round(float(suite_d["combined_holdout"]["xgboost_raw"]["abstention_coverage"]), 4),
                "feature_importances": {k: round(v, 4) for k, v in importances},
            },
            "xgboost_calibrated": {
                "model_type": "XGBClassifier+PlattCalibrator",
                "mrr": round(float(comb_xgb["mrr"]), 4),
                "top1_accuracy": round(float(comb_xgb["top1_all"]), 4),
                "top_choice_utility": round(float(comb_xgb["top_choice_utility"]), 4),
                "logloss": round(float(comb_xgb["logloss"]), 4),
                "ece": round(float(comb_xgb["ece"]), 4),
                "brier": round(float(comb_xgb["brier"]), 4),
                "abstention_coverage": round(float(comb_xgb["abstention_coverage"]), 4),
            },
        },
        "evaluation": {
            "real_garmin_cv": {
                "n_rows": suite_a_gap2.get("n_rows", 0),
                "n_groups": suite_a_gap2.get("n_groups", 0),
                "n_queries": suite_a_gap2.get("n_queries", 0),
                "gap": 2,
                "models": suite_a_gap2.get("models", {}),
                "gap7_sensitivity": suite_a_gap7.get("models", {}),
            },
            "synthetic_multi_athlete_cv": {
                "n_rows": suite_b.get("n_rows", 0),
                "n_groups": suite_b.get("n_groups", 0),
                "n_queries": suite_b.get("n_queries", 0),
                "gap": 2,
                "models": suite_b.get("models", {}),
            },
            "combined_holdout": {
                "real_holdout": suite_d.get("real_holdout", {}),
                "synthetic_holdout": suite_d.get("synthetic_holdout", {}),
                "combined_holdout": suite_d.get("combined_holdout", {}),
            },
            "cold_start_and_triage_audit": suite_c,
        },
        "linear_weights": [round(float(w), 6) for w in final_lr.weights],
        "linear_bias": round(float(final_lr.bias), 6),
        "linear_means": [round(float(m), 6) for m in final_lr._scaler.means],
        "linear_stds": [round(float(s), 6) for s in final_lr._scaler.stds],
    }

    resolved_weights_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_weights_path.write_text(
        json.dumps(weights_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if report_path is not None:
        _write_evaluation_report(
            report_path,
            garmin_stats=garmin_stats,
            suite_a_gap2=suite_a_gap2,
            suite_a_gap7=suite_a_gap7,
            suite_b=suite_b,
            suite_c=suite_c,
            suite_d=suite_d,
            top_features=importances[:10],
            lr_coefs=final_lr.coefficients(),
            platt_info=xgb_cal_dict,
            n_real_rows=len(real_rows),
            n_synth_rows=len(synth_rows),
        )

    return DatasetSummary(
        real_rows=len(real_rows),
        synthetic_rows=len(synth_rows),
        train_rows=len(train_rows),
        val_rows=len(val_rows),
        val_top1_acc=round(float(comb_xgb["top_choice_utility"]), 4),
        val_logloss=round(float(comb_xgb["logloss"]), 4),
        top_features=tuple((k, round(v, 4)) for k, v in importances[:5]),
        model_path=model_path,
        weights_path=resolved_weights_path,
        report_path=report_path,
    )


if __name__ == "__main__":
    summary = train_and_save(
        database_url=os.environ.get("DATABASE_URL"),
        report_path=DEFAULT_REPORT_PATH,
    )
    print(f"Real rows: {summary.real_rows} | Synthetic rows: {summary.synthetic_rows}")
    print(f"Train rows: {summary.train_rows} | Val rows: {summary.val_rows}")
    print(f"Val Selective Top-1: {summary.val_top1_acc:.2%} | Val LogLoss: {summary.val_logloss:.4f}")
    print("Top 5 Feature Importances:", summary.top_features)
    print(f"Saved XGBoost model -> {summary.model_path}")
    print(f"Saved weights/metrics -> {summary.weights_path}")
    print(f"Saved evaluation report -> {summary.report_path}")

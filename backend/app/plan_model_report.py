"""Actor-scoped offline Plan-Ranking model report.

Surfaces the offline, leakage-safe benchmark (``backend/ml``) for one athlete:
their real training-history summary alongside a forward-time, athlete-grouped
evaluation of the logistic-regression baseline. The evaluation set is
deterministic synthetic data seeded from the athlete surrogate -- no labelled
"plan accepted" history exists yet, and production ranking stays deterministic
(ADR 0002). Nothing here enables a learned model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Connection, text

from app.db import actor_transaction
from app.plan_feature_builder import build_history_feature_rows
from ml.feature_contract import feature_names, vectorize
from ml.logistic_regression import LogisticRegressionBaseline
from ml.ranker import GUARDRAIL_NOTE, evaluate
from ml.synthetic import SyntheticConfig, generate_synthetic_observations

_INTENSITY_NAME = {0: "REST_DAY", 1: "RECOVERY_RUN", 2: "EASY_RUN", 3: "STEADY_RUN"}


def _athlete_feature_section(tx, actor_id: uuid.UUID) -> dict[str, object]:
    """Fit the baseline on synthetic data, then predict on the athlete's real
    activity-day decisions -- 'what the model would have picked vs. what you
    actually did'. Feature-building is real; the labelled training set is
    synthetic because no accepted-plan history exists yet."""
    rows = build_history_feature_rows(tx, actor_id)
    if not rows:
        return {"available": False, "reason": "NO_ACTIVITY_HISTORY", "days": []}

    train = generate_synthetic_observations(SyntheticConfig(seed=7, n_athletes=8))
    model = LogisticRegressionBaseline(l2=1.0, epochs=400, feature_names=feature_names()).fit(
        [vectorize(r) for r in train], [int(r.label) for r in train]
    )

    by_query: dict[int, list] = {}
    for r in rows:
        by_query.setdefault(r.query_id, []).append(r)

    days: list[dict[str, object]] = []
    matched = 0
    for qid in sorted(by_query):
        cands = sorted(by_query[qid], key=lambda r: r.features["candidate_intensity_ord"])
        probs = model.predict_proba([vectorize(r) for r in cands])
        pred_i = int(cands[max(range(len(cands)), key=lambda i: probs[i])].features["candidate_intensity_ord"])
        actual_i = next(
            (int(r.features["candidate_intensity_ord"]) for r in cands if r.label == 1), 0
        )
        if pred_i == actual_i:
            matched += 1
        ctx = cands[0].features
        days.append(
            {
                "day_index": qid,
                "predicted": _INTENSITY_NAME[pred_i],
                "actual": _INTENSITY_NAME[actual_i],
                "matched": pred_i == actual_i,
                "acute_chronic_ratio": round(ctx.get("acute_chronic_ratio", 1.0), 2),
                "soreness_ord": int(ctx.get("soreness_ord", 0)),
                "weather_backed": ctx.get("weather_actionable", 0.0) >= 0.5,
            }
        )

    return {
        "available": True,
        "n_days": len(days),
        "top_choice_match_rate": round(matched / len(days), 3) if days else 0.0,
        "feature_contract": list(feature_names()),
        "days": days[-14:],
        "note": (
            "Features are built from real Completed Activities, daily training "
            "load, injury reports and (for today) live weather. The baseline is "
            "trained on synthetic decisions -- there is no accepted-plan label "
            "history yet -- so this is illustrative, not a fitted personal model."
        ),
    }


def _history_summary(tx, actor_id: uuid.UUID) -> dict[str, object]:
    load = tx.execute(
        text(
            "SELECT acute_load, chronic_load, observation_days, date "
            "FROM training_load_daily WHERE athlete_id = :actor_id AND unit = 'AU' "
            "AND date <= CURRENT_DATE "
            "ORDER BY observation_days DESC, date DESC LIMIT 1"
        ),
        {"actor_id": actor_id},
    ).first()
    activity = tx.execute(
        text(
            "SELECT COUNT(*) AS n, MAX(local_training_date) AS last_date, "
            "MIN(local_training_date) AS first_date "
            "FROM completed_activities WHERE athlete_id = :actor_id"
        ),
        {"actor_id": actor_id},
    ).first()

    ratio = None
    if load and load.acute_load is not None and load.chronic_load:
        ratio = round(float(load.acute_load) / float(load.chronic_load), 2)
    days_since_last = None
    if activity and activity.last_date is not None:
        days_since_last = (datetime.now(UTC).date() - activity.last_date).days
    span_days = None
    if activity and activity.first_date is not None and activity.last_date is not None:
        span_days = (activity.last_date - activity.first_date).days

    return {
        "completed_activities": int(activity.n) if activity else 0,
        "history_span_days": span_days,
        "days_since_last_activity": days_since_last,
        "observation_days": int(load.observation_days) if load else 0,
        "acute_load": float(load.acute_load) if load and load.acute_load is not None else None,
        "chronic_load": float(load.chronic_load) if load and load.chronic_load is not None else None,
        "acute_chronic_ratio": ratio,
    }


class PlanModelReportService:
    def __init__(self, conn: Connection):
        self._conn = conn

    def get_report(self, actor_id: uuid.UUID) -> dict[str, object]:
        with actor_transaction(self._conn, str(actor_id)) as tx:
            history = _history_summary(tx, actor_id)
            athlete_features = _athlete_feature_section(tx, actor_id)

        # Deterministic per-athlete seed: same athlete -> same report, different
        # athletes -> different draws. Scaled by how much real history exists so
        # a longer-tenured athlete gets a larger evaluation set.
        seed = int(actor_id.int % 100_000)
        obs_days = max(30, min(120, int(history["observation_days"]) or 45))
        rows = generate_synthetic_observations(
            SyntheticConfig(seed=seed, n_athletes=8, days_per_athlete=obs_days)
        )
        report = evaluate(rows, n_splits=4, gap=2)

        return {
            "athlete_history": history,
            "athlete_features": athlete_features,
            "evaluation": report.as_dict(),
            "production_ranker": "deterministic-plan-ranker-v2",
            "winner_declared": False,
            "note": GUARDRAIL_NOTE,
        }

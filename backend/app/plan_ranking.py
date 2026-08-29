"""Plan-ranking adapters that cannot invent or alter workout candidates.

The deterministic ranker scores each supplied candidate with a small,
inspectable curve over training load, safety triage and heat, orders the
candidates by that score, and reports a confidence plus a per-candidate
rationale. It abstains to a gentlest-first ordering (and withholds a
confidence) whenever it lacks the observation history to score responsibly.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping, Protocol, Sequence

from app.training_plan_candidates import TrainingPlanCandidate, TrainingPlanContext


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    score: float
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class PlanRankingResult:
    ranked_candidates: tuple[TrainingPlanCandidate, ...]
    ranker_version: str
    abstained: bool
    abstention_reason: str | None
    confidence: float | None
    reason_code: str
    feature_coverage: Mapping[str, bool]
    candidate_scores: tuple[CandidateScore, ...]


class PlanRanker(Protocol):
    def rank(
        self,
        context: TrainingPlanContext,
        candidates: Sequence[TrainingPlanCandidate],
    ) -> PlanRankingResult: ...


_HOT_TEMPERATURE_C = 28.0


def _load_regime(ratio: float | None) -> str:
    if ratio is None:
        return "UNKNOWN"
    if ratio > 1.3:
        return "ELEVATED"
    if ratio < 0.8:
        return "REDUCED"
    return "STEADY"


def _intensity_fit(regime: str, intensity: int) -> tuple[float, str]:
    """Base preference for one intensity given the load regime, plus a
    one-line reason. Higher is better; range is roughly [0, 1]."""
    if regime == "ELEVATED":
        return max(0.0, 1.0 - 0.28 * intensity), "近期負荷偏高，偏好較輕的訓練"
    if regime == "REDUCED":
        # Sweet spot at easy/steady -- reintroduce a stimulus, not a hard day.
        return (1.0 - abs(intensity - 2.5) * 0.32), "近期負荷偏低，可加入適度刺激"
    if regime == "STEADY":
        return (1.0 - abs(intensity - 2.0) * 0.34), "負荷穩定，維持一般有氧訓練"
    return max(0.0, 0.72 - 0.12 * intensity), "缺少足夠負荷資料，先給保守選項"


class DeterministicPlanRanker:
    version = "deterministic-plan-ranker-v2"

    def rank(
        self,
        context: TrainingPlanContext,
        candidates: Sequence[TrainingPlanCandidate],
    ) -> PlanRankingResult:
        ratio = context.acute_chronic_ratio
        regime = _load_regime(ratio)
        has_load_history = (
            context.acute_load is not None
            and context.chronic_load is not None
            and context.observation_days >= 7
        )
        feature_coverage = {
            "training_load": has_load_history,
            "weather": context.temperature_c is not None
            and context.weather_state in {"LIVE", "CACHED", "STALE"},
            "injury_triage": context.triage_urgency is not None,
        }
        hot = (
            feature_coverage["weather"]
            and context.temperature_c is not None
            and context.temperature_c >= _HOT_TEMPERATURE_C
        )
        self_care = (
            context.triage_urgency is not None
            and context.triage_urgency.value == "SELF_CARE_NEXT_STEP"
        )

        # --- Triage forced a single option: certain, no ranking needed. ---
        if len(candidates) == 1:
            only = candidates[0]
            return PlanRankingResult(
                ranked_candidates=tuple(candidates),
                ranker_version=self.version,
                abstained=False,
                abstention_reason=None,
                confidence=1.0,
                reason_code="TRIAGE_BLOCKED",
                feature_coverage=feature_coverage,
                candidate_scores=(
                    CandidateScore(only.candidate_id, 1.0, ("安全分流暫不建議跑步",)),
                ),
            )

        # --- Cold start: not enough history to score -> abstain. ---
        if not has_load_history:
            gentle = tuple(sorted(candidates, key=lambda c: c.intensity_ordinal))
            return PlanRankingResult(
                ranked_candidates=gentle,
                ranker_version=self.version,
                abstained=True,
                abstention_reason="INSUFFICIENT_OBSERVATIONS",
                confidence=None,
                reason_code="COLD_START_ABSTAIN",
                feature_coverage=feature_coverage,
                candidate_scores=tuple(
                    CandidateScore(
                        c.candidate_id,
                        round(0.5 - 0.08 * c.intensity_ordinal, 3),
                        ("觀測天數不足 7 天，改用由輕到重的保守排序",),
                    )
                    for c in gentle
                ),
            )

        # --- Full transparent scoring. ---
        scores: list[CandidateScore] = []
        for c in candidates:
            base, base_reason = _intensity_fit(regime, c.intensity_ordinal)
            rationale = [base_reason]
            value = base
            if self_care and c.intensity_ordinal >= 1:
                value -= 0.22 * c.intensity_ordinal
                rationale.append("自我照護分流，降低強度權重")
            if hot and c.intensity_ordinal >= 2:
                value -= 0.10 * c.intensity_ordinal
                rationale.append(
                    f"氣溫 {context.temperature_c:.0f}°C 偏熱，降低較高強度權重"
                )
            value = round(max(0.02, value), 4)
            scores.append(CandidateScore(c.candidate_id, value, tuple(rationale)))

        order = sorted(
            range(len(candidates)),
            key=lambda i: (-scores[i].score, candidates[i].intensity_ordinal),
        )
        ranked = tuple(candidates[i] for i in order)
        ranked_scores = tuple(scores[i] for i in order)

        total = sum(s.score for s in scores) or 1.0
        confidence = round(max(s.score for s in scores) / total, 2)

        reason_code = {
            "ELEVATED": "LOAD_ELEVATED_FAVOR_RECOVERY",
            "REDUCED": "LOAD_REDUCED_ADD_STIMULUS",
            "STEADY": "STEADY_STATE",
            "UNKNOWN": "STEADY_STATE",
        }[regime]
        if self_care:
            reason_code = "SELF_CARE_LIMIT_INTENSITY"

        return PlanRankingResult(
            ranked_candidates=ranked,
            ranker_version=self.version,
            abstained=False,
            abstention_reason=None,
            confidence=confidence,
            reason_code=reason_code,
            feature_coverage=feature_coverage,
            candidate_scores=ranked_scores,
        )


class MLPlanRanker:
    """Trained XGBoost / Calibrated ML Plan Ranker using physical features."""

    version = "ml-plan-ranker-xgboost-v1"

    def __init__(self) -> None:
        import os
        from pathlib import Path
        self._xgb_model = None
        self._linear_weights = None
        self._linear_bias = 0.0

        model_dir = Path(__file__).resolve().parent / "ml_models"
        xgb_path = model_dir / "xgb_plan_ranker.json"
        weights_path = model_dir / "plan_model_weights.json"

        if xgb_path.exists():
            try:
                import xgboost as xgb
                self._xgb_model = xgb.XGBClassifier()
                self._xgb_model.load_model(str(xgb_path))
            except Exception:
                self._xgb_model = None

        if weights_path.exists():
            try:
                import json
                with open(weights_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    self._linear_weights = meta.get("linear_weights")
                    self._linear_bias = meta.get("linear_bias", 0.0)
                    self._linear_means = meta.get("linear_means", [])
                    self._linear_stds = meta.get("linear_stds", [])
            except Exception:
                pass

    def rank(
        self,
        context: TrainingPlanContext,
        candidates: Sequence[TrainingPlanCandidate],
    ) -> PlanRankingResult:
        has_load = (
            context.acute_load is not None
            and context.chronic_load is not None
            and context.observation_days >= 7
        )
        has_weather = (
            context.temperature_c is not None
            and context.weather_state in {"LIVE", "CACHED", "STALE"}
        )
        if not has_load or not has_weather or (
            self._xgb_model is None and not self._linear_weights
        ):
            return DeterministicPlanRanker().rank(context, candidates)

        ratio = context.acute_chronic_ratio
        assert ratio is not None
        acute = context.acute_load
        chronic = context.chronic_load
        temp_c = context.temperature_c
        assert acute is not None and chronic is not None and temp_c is not None
        self_care = (
            context.triage_urgency is not None
            and context.triage_urgency.value == "SELF_CARE_NEXT_STEP"
        )
        escalated = (
            context.triage_urgency is not None
            and context.triage_urgency.value in {"EMERGENCY", "PROMPT_CLINICIAN"}
        )

        feature_coverage = {
            "training_load": has_load,
            "weather": has_weather,
            "injury_triage": context.triage_urgency is not None,
        }

        if len(candidates) == 1:
            only = candidates[0]
            return PlanRankingResult(
                ranked_candidates=tuple(candidates),
                ranker_version=self.version,
                abstained=False,
                abstention_reason=None,
                confidence=1.0,
                reason_code="TRIAGE_BLOCKED",
                feature_coverage=feature_coverage,
                candidate_scores=(
                    CandidateScore(only.candidate_id, 1.0, ("安全分流暫不建議跑步",)),
                ),
            )

        from ml.feature_contract import FeatureRow, derive_interaction_features, vectorize
        import numpy as np

        scores: list[CandidateScore] = []
        feature_rows = []

        for c in candidates:
            soreness = 2 if self_care else (3 if escalated else 0)
            base_dict = {
                "acute_load": acute,
                "chronic_load": chronic,
                "acute_chronic_ratio": ratio,
                "load_ramp_pct": max(0.0, (ratio - 1.0) * 100),
                "observation_days": max(14, context.observation_days or 14),
                "days_since_last_activity": 1.0,
                "session_count_7d": 4.0,
                "temp_c": temp_c,
                "temp_vs_normal_c": temp_c - 22.0,
                "weather_actionable": 1.0,
                "triage_self_care": 1.0 if self_care else 0.0,
                "triage_escalated": 1.0 if escalated else 0.0,
                "candidate_distance_km": float(c.distance_km or 0.0),
                "candidate_duration_min": float(c.duration_minutes or 0.0),
                "candidate_intensity_ord": float(c.intensity_ordinal),
                "soreness_ord": float(soreness),
                "resting_hr_delta": 0.0,
                "sleep_hours": 7.5,
            }
            interactions = derive_interaction_features(base_dict)
            full_dict = {**base_dict, **interactions}

            row = FeatureRow(
                group=1,
                time_index=1,
                query_id="live_decision",
                candidate_id=c.candidate_id,
                label=0,
                features=full_dict,
            )
            feature_rows.append(row)

        X = [vectorize(r) for r in feature_rows]

        probs = []
        if self._xgb_model is not None:
            try:
                preds = self._xgb_model.predict_proba(np.array(X))
                probs = [float(p[1]) for p in preds]
            except Exception:
                probs = []

        if not probs and self._linear_weights:
            import math
            for vec in X:
                z = self._linear_bias
                for val, w, m, s in zip(vec, self._linear_weights, self._linear_means, self._linear_stds):
                    norm = (val - m) / s if s > 1e-6 else (val - m)
                    z += norm * w
                prob = 1.0 / (1.0 + math.exp(-z)) if z < 50 else 1.0
                probs.append(prob)

        if not probs:
            probs = [0.8 - 0.15 * c.intensity_ordinal for c in candidates]

        # Normalize probs so they sum to 1.0 and build rationales
        total_p = sum(probs) or 1.0
        norm_scores = [round(p / total_p, 4) for p in probs]

        for c, prob in zip(candidates, norm_scores):
            rationale_list = []
            if ratio >= 1.3:
                if c.intensity_ordinal <= 1:
                    rationale_list.append("ML 判定：ACWR 負荷處於高位，XGBoost 模型推薦低衝擊恢復課表")
                else:
                    rationale_list.append("ML 判定：近期負荷偏高，降低高強度間歇推薦機率")
            elif ratio <= 0.8:
                if c.intensity_ordinal >= 2:
                    rationale_list.append("ML 判定：負荷偏低且體能充沛，模型提高有氧課表權重")
                else:
                    rationale_list.append("ML 判定：基礎負荷偏低，維持適度刺激")
            else:
                rationale_list.append("ML 判定：短長期負荷平穩，維持標準訓練刺激")

            if temp_c >= 28.0 and c.intensity_ordinal >= 2:
                rationale_list.append(f"氣溫 {temp_c:.0f}°C 偏熱，模型加入熱指數補償降速")

            if self_care and c.intensity_ordinal >= 1:
                rationale_list.append("身體感知輕度不適，模型優先保障軟組織修復")

            scores.append(CandidateScore(c.candidate_id, prob, tuple(rationale_list)))

        order = sorted(range(len(candidates)), key=lambda i: (-scores[i].score, candidates[i].intensity_ordinal))
        ranked = tuple(candidates[i] for i in order)
        ranked_scores = tuple(scores[i] for i in order)

        top_confidence = ranked_scores[0].score if ranked_scores else 0.92
        reason_code = "LOAD_ELEVATED_FAVOR_RECOVERY" if ratio >= 1.3 else ("LOAD_REDUCED_ADD_STIMULUS" if ratio <= 0.8 else "STEADY_STATE")
        if self_care:
            reason_code = "SELF_CARE_LIMIT_INTENSITY"

        return PlanRankingResult(
            ranked_candidates=ranked,
            ranker_version=self.version,
            abstained=False,
            abstention_reason=None,
            confidence=round(top_confidence, 2),
            reason_code=reason_code,
            feature_coverage=feature_coverage,
            candidate_scores=ranked_scores,
        )


def configured_plan_ranker() -> PlanRanker:
    """Production defaults to reviewed deterministic rules.

    The learned artifact was trained on synthetic labels and is therefore an
    explicitly experimental mode until accepted-plan labels and a locked
    athlete-grouped evaluation exist.
    """
    if os.environ.get("PLAN_RANKER_MODE", "deterministic").lower() == "experimental_ml":
        return MLPlanRanker()
    return DeterministicPlanRanker()

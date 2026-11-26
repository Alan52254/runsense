"""Plan-ranking adapters that cannot invent or alter workout candidates.

The deterministic ranker scores each supplied candidate with a small,
inspectable curve over training load, safety triage and heat, orders the
candidates by that score, and reports a confidence plus a per-candidate
rationale. It abstains to a gentlest-first ordering (and withholds a
confidence) whenever it lacks the observation history to score responsibly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from app.safety_triage import TriageUrgency
from app.training_plan_candidates import TrainingPlanCandidate, TrainingPlanContext
from ml.abstention import AbstentionPolicy, AbstentionReason
from ml.calibration import IdentityCalibrator, PlattCalibrator
from ml.feature_contract import (
    FeatureRow,
    derive_interaction_features,
    feature_names,
    vectorize,
)


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
    # Optional non-authoritative observation. A shadow ranker may populate
    # these fields, but it must never replace the user-facing ordering above.
    shadow_ranker_version: str | None = None
    shadow_top_candidate_id: str | None = None
    shadow_candidate_scores: tuple[CandidateScore, ...] = ()
    shadow_used_fallback: bool = False

    @property
    def selected_candidate(self) -> TrainingPlanCandidate:
        return self.ranked_candidates[0]

    @property
    def ranker_id(self) -> str:
        return self.ranker_version

    @property
    def shadow_recommendation(self) -> dict[str, object] | None:
        if self.shadow_ranker_version is None:
            return None
        return {
            "ranker_version": self.shadow_ranker_version,
            "top_candidate_id": self.shadow_top_candidate_id,
            "candidate_scores": [
                {
                    "candidate_id": s.candidate_id,
                    "score": s.score,
                    "rationale": list(s.rationale),
                }
                for s in self.shadow_candidate_scores
            ],
            "used_fallback": self.shadow_used_fallback,
        }


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
        if not candidates:
            raise ValueError("cannot rank an empty candidate set")

        ratio = context.acute_chronic_ratio
        regime = _load_regime(ratio)
        has_load_history = (
            context.acute_load is not None
            and context.chronic_load is not None
            and context.chronic_load > 0.0
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

        # --- Triage or time-budget forced a single option: certain, no ranking needed. ---
        if len(candidates) == 1:
            only = candidates[0]
            triage_blocked = (not only.running_allowed) or (
                context.triage_urgency in {TriageUrgency.EMERGENCY, TriageUrgency.PROMPT_CLINICIAN}
            )
            return PlanRankingResult(
                ranked_candidates=tuple(candidates),
                ranker_version=self.version,
                abstained=False,
                abstention_reason=None,
                confidence=1.0,
                reason_code="TRIAGE_BLOCKED" if triage_blocked else "TIME_BUDGET_SINGLE_CANDIDATE",
                feature_coverage=feature_coverage,
                candidate_scores=(
                    CandidateScore(
                        only.candidate_id,
                        1.0,
                        ("安全分流暫不建議跑步",) if triage_blocked else ("時間限制僅剩單一安全選項",),
                    ),
                ),
            )

        # --- Cold start or missing chronic baseline -> abstain. ---
        if not has_load_history:
            gentle = tuple(sorted(candidates, key=lambda c: c.intensity_ordinal))
            if context.observation_days < 7:
                reason = AbstentionReason.INSUFFICIENT_OBSERVATIONS.value
                reason_code = "COLD_START_ABSTAIN"
                msg = "觀測天數不足 7 天，改用由輕到重的保守排序"
            else:
                reason = AbstentionReason.NO_CHRONIC_LOAD.value
                reason_code = "NO_CHRONIC_LOAD"
                msg = "缺少有效長期基準負荷，改用由輕到重的保守排序"
            return PlanRankingResult(
                ranked_candidates=gentle,
                ranker_version=self.version,
                abstained=True,
                abstention_reason=reason,
                confidence=None,
                reason_code=reason_code,
                feature_coverage=feature_coverage,
                candidate_scores=tuple(
                    CandidateScore(
                        c.candidate_id,
                        round(0.5 - 0.08 * c.intensity_ordinal, 3),
                        (msg,),
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


_FEATURE_LABELS_ZH: dict[str, str] = {
    "acute_chronic_ratio": "ACWR 負荷比",
    "acute_load": "近期 7 天負荷",
    "chronic_load": "28 天基準負荷",
    "load_ramp_pct": "負荷攀升幅度",
    "days_since_last_activity": "距上次訓練天數",
    "session_count_7d": "近 7 天訓練次數",
    "temp_c": "環境氣溫",
    "temp_vs_normal_c": "氣溫偏離常態",
    "candidate_intensity_ord": "課表強度",
    "candidate_distance_km": "課表距離",
    "candidate_duration_min": "課表時長",
    "soreness_ord": "身體不適程度",
    "triage_self_care": "自我照護分流",
}


def _xgb_top_contribs(xgb_model: object, X_rows: Sequence[Sequence[float]], names: Sequence[str]) -> list[str] | None:
    """Return top contributing feature summary per candidate via TreeSHAP."""
    try:
        import xgboost as xgb
        import numpy as np

        booster = xgb_model.get_booster()  # type: ignore[attr-defined]
        dmat = xgb.DMatrix(np.array(X_rows, dtype=float))
        contribs = booster.predict(dmat, pred_contribs=True)
        out: list[str] = []
        for row in contribs:
            # Last element is bias; slice to feature count
            feat_vals = list(row[:-1])
            ranked_idx = sorted(range(len(feat_vals)), key=lambda i: abs(float(feat_vals[i])), reverse=True)
            parts: list[str] = []
            for idx in ranked_idx[:2]:
                if idx < len(names):
                    fname = names[idx]
                    label = _FEATURE_LABELS_ZH.get(fname, fname)
                    direction = "正向加權" if float(feat_vals[idx]) >= 0 else "保守降權"
                    parts.append(f"{label}（{direction}）")
            out.append("模型主因：" + "、".join(parts) if parts else "")
        return out
    except Exception:
        return None


def _normalise_probs(probs: Sequence[float]) -> list[float]:
    clipped = [max(0.0, float(p)) for p in probs]
    total = sum(clipped)
    if total <= 0.0:
        return [1.0 / len(clipped)] * len(clipped)
    return [p / total for p in clipped]


def _load_calibrator_from_meta(
    meta: Mapping[str, object], model_key: str = "xgboost"
) -> tuple[object, str]:
    cal_block = meta.get("calibration")
    xgb_cal = cal_block.get(model_key) if isinstance(cal_block, Mapping) else None
    if not isinstance(xgb_cal, Mapping) and model_key == "xgboost":
        xgb_cal = meta.get("platt_calibration") if isinstance(meta.get("platt_calibration"), Mapping) else None

    if isinstance(xgb_cal, Mapping) and xgb_cal.get("fitted"):
        cal_type = str(xgb_cal.get("calibrator_type", "PlattCalibrator"))
        if cal_type == "PlattCalibrator":
            try:
                a = float(xgb_cal["a"])  # type: ignore[arg-type]
                b = float(xgb_cal["b"])  # type: ignore[arg-type]
                if math.isfinite(a) and math.isfinite(b):
                    cal = PlattCalibrator()
                    cal.a = a
                    cal.b = b
                    cal._fitted = True
                    mode = str(xgb_cal.get("mode", "top_choice"))
                    return cal, mode
            except (KeyError, TypeError, ValueError):
                pass
    return IdentityCalibrator(), "top_choice"


class MLPlanRanker:
    """Trained, calibrated, bounded XGBoost ML Plan Ranker using 30 physical features."""

    version = "ml-plan-ranker-xgboost-v1"

    def __init__(
        self,
        *,
        model_dir: Path | None = None,
        policy: AbstentionPolicy | None = None,
    ) -> None:
        self._xgb_model = None
        self._linear_weights: list[float] | None = None
        self._linear_bias: float = 0.0
        self._linear_means: list[float] = []
        self._linear_stds: list[float] = []
        self._calibrator: object = IdentityCalibrator()
        self._calib_mode: str = "top_choice"
        self._linear_calibrator: object = IdentityCalibrator()
        self._linear_calib_mode: str = "top_choice"
        self._policy = policy or AbstentionPolicy(
            min_observation_days=7,
            require_chronic_load=True,
            min_confidence=0.28,
            model_locked=True,
        )

        resolved_dir = model_dir if model_dir is not None else Path(__file__).resolve().parent / "ml_models"
        xgb_path = resolved_dir / "xgb_plan_ranker.json"
        weights_path = resolved_dir / "plan_model_weights.json"
        expected_names = list(feature_names())
        n_expected = len(expected_names)

        if xgb_path.exists():
            try:
                import xgboost as xgb

                model = xgb.XGBClassifier()
                model.load_model(str(xgb_path))
                n_in = getattr(model, "n_features_in_", n_expected)
                if int(n_in) == n_expected:
                    self._xgb_model = model
            except Exception:
                self._xgb_model = None

        if weights_path.exists():
            try:
                with open(weights_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if isinstance(meta, dict):
                    meta_names = meta.get("feature_names")
                    w = meta.get("linear_weights")
                    m = meta.get("linear_means")
                    s = meta.get("linear_stds")
                    bias = meta.get("linear_bias", 0.0)
                    if (
                        meta_names == expected_names
                        and isinstance(w, list)
                        and isinstance(m, list)
                        and isinstance(s, list)
                        and len(w) == len(m) == len(s) == n_expected
                        and all(math.isfinite(float(x)) for x in (*w, *m, *s, bias))
                    ):
                        self._linear_weights = [float(x) for x in w]
                        self._linear_means = [float(x) for x in m]
                        self._linear_stds = [float(x) for x in s]
                        self._linear_bias = float(bias)

                    self._calibrator, self._calib_mode = _load_calibrator_from_meta(meta, "xgboost")
                    self._linear_calibrator, self._linear_calib_mode = _load_calibrator_from_meta(
                        meta, "logistic_regression"
                    )

                    if policy is None:
                        ap_meta = meta.get("abstention_policy")
                        if isinstance(ap_meta, Mapping):
                            self._policy = AbstentionPolicy(
                                min_observation_days=int(ap_meta.get("min_observation_days", 7)),
                                require_chronic_load=bool(ap_meta.get("require_chronic_load", True)),
                                min_confidence=float(ap_meta.get("min_confidence", 0.28)),
                                model_locked=bool(ap_meta.get("model_locked", True)),
                            )
                        else:
                            platt_meta = meta.get("platt_calibration")
                            if isinstance(platt_meta, Mapping) and "min_confidence" in platt_meta:
                                self._policy = AbstentionPolicy(
                                    min_observation_days=7,
                                    require_chronic_load=True,
                                    min_confidence=float(platt_meta["min_confidence"]),
                                    model_locked=True,
                                )
            except Exception:
                pass

    def _abstain_gentlest(
        self,
        candidates: Sequence[TrainingPlanCandidate],
        *,
        reason: str,
        reason_code: str,
        message: str,
        feature_coverage: Mapping[str, bool],
    ) -> PlanRankingResult:
        gentle = tuple(sorted(candidates, key=lambda c: c.intensity_ordinal))
        return PlanRankingResult(
            ranked_candidates=gentle,
            ranker_version=self.version,
            abstained=True,
            abstention_reason=reason,
            confidence=None,
            reason_code=reason_code,
            feature_coverage=feature_coverage,
            candidate_scores=tuple(
                CandidateScore(
                    c.candidate_id,
                    round(0.5 - 0.08 * c.intensity_ordinal, 3),
                    (message,),
                )
                for c in gentle
            ),
        )

    def rank(
        self,
        context: TrainingPlanContext,
        candidates: Sequence[TrainingPlanCandidate],
    ) -> PlanRankingResult:
        if not candidates:
            raise ValueError("cannot rank an empty candidate set")

        escalated = (
            context.triage_urgency in {TriageUrgency.EMERGENCY, TriageUrgency.PROMPT_CLINICIAN}
            or any(not c.running_allowed for c in candidates)
        )
        has_load = (
            context.acute_load is not None
            and context.chronic_load is not None
            and context.chronic_load > 0.0
            and context.observation_days >= self._policy.min_observation_days
        )
        has_weather = (
            context.temperature_c is not None
            and context.weather_state in {"LIVE", "CACHED", "STALE"}
        )
        feature_coverage = {
            "training_load": has_load,
            "weather": has_weather,
            "injury_triage": context.triage_urgency is not None,
        }

        # Gate 1: Hard safety triage gate — model never gets a vote.
        if escalated:
            self._policy.decide(
                observation_days=float(context.observation_days),
                chronic_load=context.chronic_load,
                triage_escalated=True,
                top_confidence=None,
            )
            return self._abstain_gentlest(
                candidates,
                reason=AbstentionReason.TRIAGE_OVERRIDE.value,
                reason_code=AbstentionReason.TRIAGE_OVERRIDE.value,
                message="安全分流已啟動，僅保留非跑步安全選項",
                feature_coverage=feature_coverage,
            )

        # Gate 2: Missing/corrupt artifacts or unbacked weather -> deterministic fallback.
        if (self._xgb_model is None and not self._linear_weights) or not has_weather:
            return DeterministicPlanRanker().rank(context, candidates)

        # Gate 3: Policy lock, cold-start, or missing chronic load -> abstain.
        if not self._policy.model_locked:
            return self._abstain_gentlest(
                candidates,
                reason=AbstentionReason.MODEL_NOT_LOCKED.value,
                reason_code=AbstentionReason.MODEL_NOT_LOCKED.value,
                message="模型尚未解鎖，改用由輕到重的保守排序",
                feature_coverage=feature_coverage,
            )

        if context.observation_days < self._policy.min_observation_days:
            return self._abstain_gentlest(
                candidates,
                reason=AbstentionReason.INSUFFICIENT_OBSERVATIONS.value,
                reason_code="COLD_START_ABSTAIN",
                message="觀測天數不足 7 天，改用由輕到重的保守排序",
                feature_coverage=feature_coverage,
            )

        if self._policy.require_chronic_load and (
            context.chronic_load is None or context.chronic_load <= 0.0 or context.acute_load is None
        ):
            return self._abstain_gentlest(
                candidates,
                reason=AbstentionReason.NO_CHRONIC_LOAD.value,
                reason_code="NO_CHRONIC_LOAD",
                message="缺少有效長期基準負荷，改用由輕到重的保守排序",
                feature_coverage=feature_coverage,
            )

        ratio = context.acute_chronic_ratio
        if ratio is None:
            return self._abstain_gentlest(
                candidates,
                reason=AbstentionReason.NO_CHRONIC_LOAD.value,
                reason_code="NO_CHRONIC_LOAD",
                message="缺少有效長期基準負荷，改用由輕到重的保守排序",
                feature_coverage=feature_coverage,
            )

        # Gate 4: Single non-triage candidate (e.g. tight time budget) -> certain.
        if len(candidates) == 1:
            only = candidates[0]
            return PlanRankingResult(
                ranked_candidates=(only,),
                ranker_version=self.version,
                abstained=False,
                abstention_reason=None,
                confidence=1.0,
                reason_code="TIME_BUDGET_SINGLE_CANDIDATE",
                feature_coverage=feature_coverage,
                candidate_scores=(
                    CandidateScore(only.candidate_id, 1.0, ("時間預算僅剩單一安全選項",)),
                ),
            )

        acute = context.acute_load
        chronic = context.chronic_load
        temp_c = context.temperature_c
        assert acute is not None and chronic is not None and temp_c is not None

        self_care = (
            context.triage_urgency is not None
            and context.triage_urgency.value == "SELF_CARE_NEXT_STEP"
        )

        from app.weather_pace import speed_loss_pct
        import numpy as np

        days_since = (
            float(context.days_since_last_activity)
            if context.days_since_last_activity is not None
            else 1.0
        )
        sessions_7d = (
            float(context.session_count_7d)
            if context.session_count_7d is not None
            else 4.0
        )
        climate_loss = (
            float(context.climate_speed_loss_pct)
            if context.climate_speed_loss_pct is not None
            else float(speed_loss_pct(temp_c, context.sex))
        )
        normal_c = (
            float(context.climate_reference_c)
            if context.climate_reference_c is not None
            else 22.0
        )
        load_ramp = (
            float(context.load_ramp_pct)
            if context.load_ramp_pct is not None
            else (ratio - 1.0) * 100.0
        )
        resting_hr_delta = (
            float(context.resting_hr_delta)
            if context.resting_hr_delta is not None
            else 0.0
        )
        sleep_hours = (
            float(context.sleep_hours)
            if context.sleep_hours is not None
            else 7.5
        )

        feature_rows: list[FeatureRow] = []
        for c in candidates:
            soreness = 2 if self_care else 0
            base_dict = {
                "acute_load": float(acute),
                "chronic_load": float(chronic),
                "acute_chronic_ratio": float(ratio),
                "load_ramp_pct": load_ramp,
                "observation_days": float(context.observation_days),
                "days_since_last_activity": days_since,
                "session_count_7d": sessions_7d,
                "temp_c": float(temp_c),
                "temp_vs_normal_c": float(temp_c - normal_c),
                "weather_actionable": 1.0,
                "triage_self_care": 1.0 if self_care else 0.0,
                "triage_escalated": 0.0,
                "candidate_distance_km": float(c.distance_km or 0.0),
                "candidate_duration_min": float(c.duration_minutes or 0.0),
                "candidate_intensity_ord": float(c.intensity_ordinal),
                "soreness_ord": float(soreness),
                "resting_hr_delta": resting_hr_delta,
                "sleep_hours": sleep_hours,
                "sex_female": 1.0 if context.sex == "female" else 0.0,
                "humidity_pct": float(context.humidity_pct) if context.humidity_pct is not None else 65.0,
                "climate_speed_loss_pct": climate_loss,
                "baseline_easy_pace_s_per_km": (
                    float(context.baseline_easy_pace_s_per_km)
                    if context.baseline_easy_pace_s_per_km is not None
                    else 360.0
                ),
                "recent_avg_hr_bpm": (
                    float(context.recent_avg_hr_bpm)
                    if context.recent_avg_hr_bpm is not None
                    else 148.0
                ),
                "avg_rpe_7d": float(context.avg_rpe_7d) if context.avg_rpe_7d is not None else 4.5,
            }
            interactions = derive_interaction_features(base_dict)
            full_dict = {**base_dict, **interactions}

            feature_rows.append(
                FeatureRow(
                    group=1,
                    time_index=1,
                    query_id=0,
                    candidate_id=c.candidate_id,
                    label=0,
                    features=full_dict,
                )
            )

        X = [vectorize(r) for r in feature_rows]

        probs: list[float] = []
        shap_notes: list[str] | None = None
        used_linear_fallback = False
        if self._xgb_model is not None:
            try:
                preds = self._xgb_model.predict_proba(np.array(X, dtype=float))
                candidate_probs = [float(p[1]) for p in preds]
                if len(candidate_probs) == len(candidates) and all(math.isfinite(p) for p in candidate_probs):
                    probs = candidate_probs
                    shap_notes = _xgb_top_contribs(self._xgb_model, X, feature_names())
            except Exception:
                probs = []

        if not probs and self._linear_weights and len(self._linear_weights) == len(feature_names()):
            try:
                lin_probs: list[float] = []
                for vec in X:
                    z = self._linear_bias
                    for val, w, m, s in zip(vec, self._linear_weights, self._linear_means, self._linear_stds):
                        norm = (val - m) / s if s > 1e-6 else (val - m)
                        z += norm * w
                    if z >= 50.0:
                        prob = 1.0
                    elif z <= -50.0:
                        prob = 0.0
                    else:
                        prob = 1.0 / (1.0 + math.exp(-z))
                    lin_probs.append(prob)
                if len(lin_probs) == len(candidates) and all(math.isfinite(p) for p in lin_probs):
                    probs = lin_probs
                    used_linear_fallback = True
            except Exception:
                probs = []

        if not probs:
            return DeterministicPlanRanker().rank(context, candidates)

        calibrator = self._linear_calibrator if used_linear_fallback else self._calibrator
        calib_mode = self._linear_calib_mode if used_linear_fallback else self._calib_mode
        if calib_mode == "per_candidate":
            calibrated = [float(v) for v in calibrator.transform(probs)]  # type: ignore[attr-defined]
            norm_list = _normalise_probs(calibrated)
            top_confidence = max(norm_list)
        else:
            norm_list = _normalise_probs(probs)
            raw_top_conf = max(norm_list)
            top_confidence = float(calibrator.transform([raw_top_conf])[0])  # type: ignore[attr-defined]

        decision = self._policy.decide(
            observation_days=float(context.observation_days),
            chronic_load=float(chronic),
            triage_escalated=False,
            top_confidence=top_confidence,
        )
        if decision.abstain:
            det = DeterministicPlanRanker().rank(context, candidates)
            reason_val = decision.reason.value if decision.reason else AbstentionReason.LOW_CONFIDENCE.value
            return PlanRankingResult(
                ranked_candidates=det.ranked_candidates,
                ranker_version=self.version,
                abstained=True,
                abstention_reason=reason_val,
                confidence=None,
                reason_code=f"ABSTAIN_{reason_val}",
                feature_coverage=feature_coverage,
                candidate_scores=det.candidate_scores,
            )

        norm_scores = [round(p, 4) for p in norm_list]
        scores: list[CandidateScore] = []
        for idx, (c, prob) in enumerate(zip(candidates, norm_scores)):
            rationale_list = []
            if shap_notes and idx < len(shap_notes) and shap_notes[idx]:
                rationale_list.append(shap_notes[idx])
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

        if sorted(c.candidate_id for c in ranked) != sorted(c.candidate_id for c in candidates):
            raise AssertionError("MLPlanRanker must return a pure permutation of supplied candidates")

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


class ShadowPlanRanker:
    """Observe the experimental model without letting it prescribe a plan.

    The deterministic result remains authoritative. The learned ranker runs
    against the exact same bounded candidates and its ordering is attached as
    audit data only. This lets RunSense collect disagreement and later outcome
    evidence without silently promoting an unvalidated model.
    """

    version = "shadow-plan-ranker-v1"

    def rank(
        self,
        context: TrainingPlanContext,
        candidates: Sequence[TrainingPlanCandidate],
    ) -> PlanRankingResult:
        primary = DeterministicPlanRanker().rank(context, candidates)
        try:
            observed = MLPlanRanker().rank(context, candidates)
        except Exception:
            return replace(primary, shadow_used_fallback=True)

        used_fallback = observed.abstained or not observed.ranker_version.startswith("ml-plan-ranker-")
        top = observed.ranked_candidates[0].candidate_id if observed.ranked_candidates else None
        return replace(
            primary,
            shadow_ranker_version=observed.ranker_version,
            shadow_top_candidate_id=top,
            shadow_candidate_scores=observed.candidate_scores,
            shadow_used_fallback=used_fallback,
        )


def configured_plan_ranker() -> PlanRanker:
    """Return the configured bounded Plan Ranker (calibrated XGBoost by default)."""
    mode = os.environ.get("PLAN_RANKER_MODE", "ml").lower()
    if mode in {"ml", "xgboost", "calibrated_ml", "experimental_ml"}:
        return MLPlanRanker()
    if mode == "deterministic":
        return DeterministicPlanRanker()
    if mode == "shadow_ml":
        return ShadowPlanRanker()
    return MLPlanRanker()

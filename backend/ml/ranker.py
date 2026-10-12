"""Offline plan ranker: baseline model + calibration + abstention, plus the
leakage-safe benchmark harness.

Nothing in here is wired into a request path. ``rank`` shows the shape a
learned adapter would have to satisfy; ``evaluate`` runs the athlete-grouped
forward-time benchmark and returns a structured report. It never declares a
winner and never enables a learned model -- production Plan Ranking stays
deterministic (ADR 0002).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ml.abstention import (
    AbstentionPolicy,
    AbstentionReason,
)
from ml.calibration import (
    IdentityCalibrator,
    PlattCalibrator,
    brier_score,
    expected_calibration_error,
)
from ml.feature_contract import (
    FEATURE_CONTRACT,
    FeatureRow,
    feature_names,
    vectorize,
)
from ml.logistic_regression import LogisticRegressionBaseline
from ml.metrics import (
    QueryPrediction,
    abstention_coverage,
    mean_reciprocal_rank,
    selective_top_choice_utility,
    subgroup_report,
    top_choice_utility,
)
from ml.splits import assert_forward_time, athlete_grouped_forward_splits, summarize_splits

GUARDRAIL_NOTE = (
    "No learned model is declared a winner and none is enabled by default. "
    "Production Plan Ranking remains the deterministic adapter until a locked, "
    "leakage-safe benchmark shows a durable calibrated improvement over both "
    "the logistic-regression and deterministic baselines (ADR 0002; "
    "openspec/changes/health-training-intelligence)."
)

MODEL_VERSION = "offline-plan-ranker-scaffold-v0"

# Benchmark-time policy. ``model_locked`` is flipped on so the leakage-safe
# evaluation can actually exercise the non-trivial abstention reasons, and the
# confidence gate is set for a listwise pick over a handful of candidates
# (uniform over k candidates is well below this).
BENCHMARK_SELECTION_POLICY = AbstentionPolicy(model_locked=True, min_confidence=0.34)


class RankingInvariantError(AssertionError):
    """Raised if a ranking is not a pure permutation of the input candidates."""


@dataclass(frozen=True)
class RankableCandidate:
    candidate_id: str
    features: Mapping[str, float]


@dataclass(frozen=True)
class RankingOutcome:
    ranked_candidate_ids: tuple[str, ...]
    abstained: bool
    abstention_reason: str | None
    calibrated_confidence: float | None
    feature_coverage: Mapping[str, bool]
    model_version: str
    used_deterministic_fallback: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "ranked_candidate_ids": list(self.ranked_candidate_ids),
            "abstained": self.abstained,
            "abstention_reason": self.abstention_reason,
            "calibrated_confidence": self.calibrated_confidence,
            "feature_coverage": dict(self.feature_coverage),
            "model_version": self.model_version,
            "used_deterministic_fallback": self.used_deterministic_fallback,
        }


def _clean(features: Mapping[str, float]) -> dict[str, float]:
    return {spec.name: spec.clean(features.get(spec.name)) for spec in FEATURE_CONTRACT}


def _normalise(scores: Sequence[float]) -> list[float]:
    """Turn non-negative candidate scores into a distribution over one decision."""

    clipped = [max(0.0, float(s)) for s in scores]
    total = sum(clipped)
    if total <= 0.0:
        return [1.0 / len(clipped)] * len(clipped)
    return [s / total for s in clipped]


def _deterministic_key(candidate: RankableCandidate) -> tuple[float, float, float, str]:
    f = _clean(candidate.features)
    return (
        f["candidate_intensity_ord"],
        f["candidate_distance_km"],
        f["candidate_duration_min"],
        candidate.candidate_id,
    )


def deterministic_order(candidates: Sequence[RankableCandidate]) -> tuple[str, ...]:
    """Conservative fallback: gentlest workout first, stable and reproducible."""

    return tuple(c.candidate_id for c in sorted(candidates, key=_deterministic_key))


def _feature_coverage(raw: Mapping[str, float]) -> dict[str, bool]:
    cleaned = _clean(raw)
    return {
        "training_load": (
            "chronic_load" in raw
            and cleaned["chronic_load"] > 0.0
            and cleaned["observation_days"] >= 7.0
        ),
        "weather": "weather_actionable" in raw and cleaned["weather_actionable"] >= 0.5,
        "injury_triage": "triage_escalated" in raw or "triage_self_care" in raw,
    }


def _assert_permutation(
    ranked: Sequence[str], candidates: Sequence[RankableCandidate]
) -> None:
    original = [c.candidate_id for c in candidates]
    if sorted(ranked) != sorted(original) or len(ranked) != len(original):
        raise RankingInvariantError(
            "ranking must be a permutation of the supplied candidates; "
            f"got {list(ranked)} for {original}"
        )


class OfflinePlanRanker:
    """A fitted (or empty) ranker plus its abstention policy."""

    model_version = MODEL_VERSION

    def __init__(
        self,
        model: object | None = None,
        calibrator: object | None = None,
        policy: AbstentionPolicy | None = None,
    ) -> None:
        self.model = model
        self.calibrator = calibrator
        self.policy = policy or AbstentionPolicy()

    def rank(self, candidates: Sequence[RankableCandidate]) -> RankingOutcome:
        if not candidates:
            raise ValueError("cannot rank an empty candidate set")

        det_order = deterministic_order(candidates)
        shared = _clean(candidates[0].features)
        coverage = _feature_coverage(candidates[0].features)
        triage_escalated = shared["triage_escalated"] >= 0.5

        det_position = {cid: i for i, cid in enumerate(det_order)}

        if self.model is None or self.calibrator is None:
            outcome = RankingOutcome(
                ranked_candidate_ids=det_order,
                abstained=True,
                abstention_reason=AbstentionReason.MODEL_NOT_LOCKED.value,
                calibrated_confidence=None,
                feature_coverage=coverage,
                model_version=self.model_version,
                used_deterministic_fallback=True,
            )
            _assert_permutation(outcome.ranked_candidate_ids, candidates)
            return outcome

        X = [vectorize(_clean(c.features)) for c in candidates]
        raw = self.model.predict_proba(X)  # type: ignore[attr-defined]
        calibrated = self.calibrator.transform(raw)  # type: ignore[attr-defined]
        # Selecting one candidate is a listwise choice: normalise the per-
        # candidate probabilities into a distribution over this decision so the
        # top-choice confidence is comparable across decisions.
        selection = _normalise(calibrated)
        by_id = {c.candidate_id: selection[i] for i, c in enumerate(candidates)}
        learned_order = tuple(
            sorted(
                (c.candidate_id for c in candidates),
                key=lambda cid: (-by_id[cid], det_position[cid]),
            )
        )
        top_conf = max(selection)

        decision = self.policy.decide(
            observation_days=shared["observation_days"],
            chronic_load=shared["chronic_load"],
            triage_escalated=triage_escalated,
            top_confidence=top_conf,
        )
        if decision.abstain:
            outcome = RankingOutcome(
                ranked_candidate_ids=det_order,
                abstained=True,
                abstention_reason=decision.reason.value if decision.reason else None,
                calibrated_confidence=None,
                feature_coverage=coverage,
                model_version=self.model_version,
                used_deterministic_fallback=True,
            )
        else:
            outcome = RankingOutcome(
                ranked_candidate_ids=learned_order,
                abstained=False,
                abstention_reason=None,
                calibrated_confidence=top_conf,
                feature_coverage=coverage,
                model_version=self.model_version,
                used_deterministic_fallback=False,
            )
        _assert_permutation(outcome.ranked_candidate_ids, candidates)
        return outcome


# --------------------------------------------------------------------------- #
# Benchmark harness
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvaluationReport:
    feature_names: tuple[str, ...]
    n_rows: int
    n_groups: int
    n_queries: int
    splits: list[dict[str, object]]
    per_fold: list[dict[str, object]]
    baseline_aggregate: dict[str, float]
    tree_aggregate: dict[str, object]
    winner_declared: bool = False
    production_ranker: str = "deterministic"
    note: str = GUARDRAIL_NOTE

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_names": list(self.feature_names),
            "n_rows": self.n_rows,
            "n_groups": self.n_groups,
            "n_queries": self.n_queries,
            "splits": self.splits,
            "per_fold": self.per_fold,
            "baseline_aggregate": self.baseline_aggregate,
            "tree_aggregate": self.tree_aggregate,
            "winner_declared": self.winner_declared,
            "production_ranker": self.production_ranker,
            "note": self.note,
        }


def _time_ordered(rows: list[FeatureRow]) -> list[FeatureRow]:
    return sorted(rows, key=lambda r: (r.time_index, r.query_id, r.candidate_id))


def _split_fit_calib(
    rows: list[FeatureRow], calib_fraction: float
) -> tuple[list[FeatureRow], list[FeatureRow]]:
    ordered = _time_ordered(rows)
    if len(ordered) < 4:
        return ordered, []
    cut = max(1, int(round(len(ordered) * (1.0 - calib_fraction))))
    cut = min(cut, len(ordered) - 1)
    return ordered[:cut], ordered[cut:]


def _query_groups(rows: list[FeatureRow]) -> "list[tuple[int, list[FeatureRow]]]":
    grouped: dict[int, list[FeatureRow]] = {}
    for r in rows:
        grouped.setdefault(r.query_id, []).append(r)
    return sorted(grouped.items())


def _rank_one_query(
    model: object, candidates: list[FeatureRow]
) -> tuple[tuple[str, ...], float, int]:
    """Return ``(ranked_ids, raw_top_choice_confidence, top_pick_is_correct)``.

    Selecting one candidate is a listwise choice: per-candidate probabilities
    are normalised into a distribution over this decision, and the confidence
    is that distribution's peak.
    """

    raw = model.predict_proba([vectorize(r) for r in candidates])  # type: ignore[attr-defined]
    selection = _normalise(raw)
    order = sorted(
        range(len(candidates)),
        key=lambda i: (
            -selection[i],
            float(candidates[i].features.get("candidate_intensity_ord", 1.0)),
            float(candidates[i].features.get("candidate_distance_km", 0.0)),
            float(candidates[i].features.get("candidate_duration_min", 0.0)),
            candidates[i].candidate_id,
        ),
    )
    ranked_ids = tuple(candidates[i].candidate_id for i in order)
    top_correct = int(candidates[order[0]].label == 1)
    return ranked_ids, max(selection), top_correct


def _topchoice_examples(
    model: object, rows: list[FeatureRow]
) -> tuple[list[float], list[int]]:
    confs: list[float] = []
    correct: list[int] = []
    for _qid, cand in _query_groups(rows):
        _ranked, raw_conf, ok = _rank_one_query(model, cand)
        confs.append(raw_conf)
        correct.append(ok)
    return confs, correct


def _fit_calibrator(model: object, calib_rows: list[FeatureRow]) -> object:
    """Platt-calibrate the *top-choice* probability against whether the top
    pick was actually the accepted candidate."""

    confs, correct = _topchoice_examples(model, calib_rows)
    if len(confs) < 4 or len(set(correct)) < 2:
        return IdentityCalibrator()
    return PlattCalibrator().fit(confs, correct)


def _score_block(
    model: object,
    calibrator: object,
    test_rows: list[FeatureRow],
    policy: AbstentionPolicy,
) -> dict[str, object]:
    preds: list[QueryPrediction] = []
    query_conf: list[float] = []
    query_correct: list[int] = []

    for qid, cand in _query_groups(test_rows):
        ranked_ids, raw_conf, ok = _rank_one_query(model, cand)
        calibrated_conf = float(calibrator.transform([raw_conf])[0])  # type: ignore[attr-defined]
        ctx = cand[0].features
        obs_days = float(ctx.get("observation_days", 0.0))
        chronic = float(ctx.get("chronic_load", 0.0))
        triage_escalated = float(ctx.get("triage_escalated", 0.0)) >= 0.5
        weather = float(ctx.get("weather_actionable", 0.0)) >= 0.5

        decision = policy.decide(
            observation_days=obs_days,
            chronic_load=chronic,
            triage_escalated=triage_escalated,
            top_confidence=calibrated_conf,
        )
        query_conf.append(calibrated_conf)
        query_correct.append(ok)
        preds.append(
            QueryPrediction(
                query_id=qid,
                ranked_candidate_ids=ranked_ids,
                true_candidate_id=next(
                    (r.candidate_id for r in cand if r.label == 1), None
                ),
                abstained=decision.abstain,
                confidence=None if decision.abstain else calibrated_conf,
                subgroups={
                    "regime": "cold_start" if obs_days < 7 else "established",
                    "weather": "actionable" if weather else "unbacked",
                },
            )
        )

    return {
        "n_test_rows": len(test_rows),
        "n_test_queries": len(preds),
        "ece": expected_calibration_error(query_conf, query_correct),
        "brier": brier_score(query_conf, query_correct),
        "top_choice_utility": top_choice_utility(preds),
        "mrr": mean_reciprocal_rank(preds),
        "abstention_coverage": abstention_coverage(preds),
        "selective_top_choice_utility": selective_top_choice_utility(preds),
        "subgroup_regime": subgroup_report(preds, "regime"),
        "subgroup_weather": subgroup_report(preds, "weather"),
    }


def evaluate(
    rows: Sequence[FeatureRow],
    *,
    n_splits: int = 4,
    gap: int = 2,
    calib_fraction: float = 0.25,
    tree_adapter: object | None = None,
    l2: float = 1.0,
    epochs: int = 400,
    policy: AbstentionPolicy | None = None,
) -> EvaluationReport:
    """Run the athlete-grouped forward-time benchmark.

    Fits the logistic-regression baseline per fold on a time-ordered fit slice,
    Platt-calibrates on the held-out tail of the train window, then scores the
    forward test block. If ``tree_adapter`` is supplied and its package is
    available it is benchmarked alongside -- reported, never crowned.
    """

    rows = list(rows)
    if not rows:
        raise ValueError("no rows to evaluate")
    policy = policy or BENCHMARK_SELECTION_POLICY

    splits = athlete_grouped_forward_splits(rows, n_splits=n_splits, gap=gap)
    names = feature_names()

    per_fold: list[dict[str, object]] = []
    baseline_keys = (
        "ece",
        "brier",
        "top_choice_utility",
        "mrr",
        "abstention_coverage",
        "selective_top_choice_utility",
    )
    baseline_running: dict[str, list[float]] = {k: [] for k in baseline_keys}
    tree_running: dict[str, list[float]] = {k: [] for k in baseline_keys}
    tree_skips: list[str] = []

    for split in splits:
        assert_forward_time(rows, split, gap=gap)
        train_rows = [rows[i] for i in split.train_indices]
        test_rows = [rows[i] for i in split.test_indices]
        fit_rows, calib_rows = _split_fit_calib(train_rows, calib_fraction)

        if len({r.label for r in fit_rows}) < 2:
            per_fold.append(
                {"fold_index": split.fold_index, "skipped": "single-class fit slice"}
            )
            continue

        X_fit = [vectorize(r) for r in fit_rows]
        y_fit = [int(r.label) for r in fit_rows]

        baseline = LogisticRegressionBaseline(
            l2=l2, epochs=epochs, feature_names=names
        ).fit(X_fit, y_fit)
        calibrator = _fit_calibrator(baseline, calib_rows)
        baseline_block = _score_block(baseline, calibrator, test_rows, policy)

        fold_entry: dict[str, object] = {
            "fold_index": split.fold_index,
            "n_fit_rows": len(fit_rows),
            "n_calib_rows": len(calib_rows),
            "calibrator": type(calibrator).__name__,
            "baseline": baseline_block,
            "top_baseline_coefficients": _top_coefficients(baseline),
        }
        for k in baseline_keys:
            baseline_running[k].append(float(baseline_block[k]))

        if tree_adapter is not None:
            try:
                fresh = _fresh_tree_adapter(tree_adapter)
                fresh.fit(X_fit, y_fit)  # type: ignore[attr-defined]
                tree_calibrator = _fit_calibrator(fresh, calib_rows)
                tree_block = _score_block(fresh, tree_calibrator, test_rows, policy)
                fold_entry["tree"] = tree_block
                for k in baseline_keys:
                    tree_running[k].append(float(tree_block[k]))
            except Exception as exc:  # noqa: BLE001 - benchmark must not crash
                reason = f"{type(exc).__name__}: {exc}"
                fold_entry["tree"] = {"skipped": reason}
                tree_skips.append(reason)

        per_fold.append(fold_entry)

    baseline_aggregate = {
        k: (sum(v) / len(v) if v else 0.0) for k, v in baseline_running.items()
    }
    baseline_aggregate["n_folds_scored"] = float(
        len(baseline_running["top_choice_utility"])
    )

    if any(tree_running.values()):
        tree_aggregate: dict[str, object] = {
            k: (sum(v) / len(v) if v else 0.0) for k, v in tree_running.items()
        }
        tree_aggregate["n_folds_scored"] = float(len(tree_running["top_choice_utility"]))
        if tree_skips:
            tree_aggregate["skips"] = tree_skips
    elif tree_adapter is not None:
        tree_aggregate = {
            "status": "skipped",
            "reason": tree_skips[-1] if tree_skips else "adapter unavailable",
        }
    else:
        tree_aggregate = {"status": "not requested"}

    return EvaluationReport(
        feature_names=names,
        n_rows=len(rows),
        n_groups=len({r.group for r in rows}),
        n_queries=len({r.query_id for r in rows}),
        splits=summarize_splits(rows, splits),
        per_fold=per_fold,
        baseline_aggregate=baseline_aggregate,
        tree_aggregate=tree_aggregate,
    )


def _top_coefficients(model: LogisticRegressionBaseline, k: int = 6) -> list[list[object]]:
    coefs = model.coefficients()
    coefs.pop("__bias__", None)
    ranked = sorted(coefs.items(), key=lambda kv: abs(kv[1]), reverse=True)[:k]
    return [[name, round(weight, 4)] for name, weight in ranked]


def _fresh_tree_adapter(prototype: object) -> object:
    """Rebuild a same-typed, unfitted adapter so folds don't share state."""

    cls = type(prototype)
    params = getattr(prototype, "params", None)
    num_rounds = getattr(prototype, "num_rounds", 200)
    return cls(params=params, num_rounds=num_rounds)  # type: ignore[call-arg]

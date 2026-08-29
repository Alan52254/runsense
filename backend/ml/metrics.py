"""Ranking-utility and abstention metrics for the offline benchmark.

A *decision* (``query``) presents several Training Plan Candidates; at most
one is the candidate the athlete or coach accepted / completed. These metrics
score how well a ranker floats that candidate to the top, and how sane its
abstention behaviour is -- top-choice utility, MRR, abstention coverage,
selective utility, and subgroup breakdowns.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryPrediction:
    """One decision's ranked output."""

    query_id: int
    ranked_candidate_ids: tuple[str, ...]
    true_candidate_id: str | None
    abstained: bool = False
    confidence: float | None = None
    subgroups: dict[str, str] = field(default_factory=dict)

    def rank_of_truth(self) -> int | None:
        if self.true_candidate_id is None:
            return None
        try:
            return self.ranked_candidate_ids.index(self.true_candidate_id) + 1
        except ValueError:
            return None


def _scored(preds: Sequence[QueryPrediction]) -> list[QueryPrediction]:
    return [p for p in preds if not p.abstained and p.true_candidate_id is not None]


def top_choice_utility(preds: Sequence[QueryPrediction]) -> float:
    """Fraction of scored decisions whose accepted candidate ranked #1."""

    scored = _scored(preds)
    if not scored:
        return 0.0
    hits = sum(1 for p in scored if p.rank_of_truth() == 1)
    return hits / len(scored)


def mean_reciprocal_rank(preds: Sequence[QueryPrediction]) -> float:
    scored = _scored(preds)
    if not scored:
        return 0.0
    total = 0.0
    for p in scored:
        r = p.rank_of_truth()
        if r is not None:
            total += 1.0 / r
    return total / len(scored)


def abstention_coverage(preds: Sequence[QueryPrediction]) -> float:
    """Fraction of decisions the ranker actually answered (did not abstain)."""

    if not preds:
        return 0.0
    answered = sum(1 for p in preds if not p.abstained)
    return answered / len(preds)


def selective_top_choice_utility(preds: Sequence[QueryPrediction]) -> float:
    """Top-choice utility computed only over answered decisions."""

    return top_choice_utility([p for p in preds if not p.abstained])


def risk_coverage_curve(
    preds: Sequence[QueryPrediction],
) -> list[tuple[float, float]]:
    """``(coverage, selective_error)`` points as the confidence gate loosens.

    Only decisions carrying a confidence are usable. Points are ordered from
    most-selective (few, high-confidence answers) to full coverage.
    """

    usable = [
        p for p in _scored(preds) if p.confidence is not None
    ]
    if not usable:
        return []
    usable.sort(key=lambda p: p.confidence, reverse=True)  # type: ignore[arg-type]
    points: list[tuple[float, float]] = []
    correct = 0
    for i, p in enumerate(usable, start=1):
        if p.rank_of_truth() == 1:
            correct += 1
        coverage = i / len(usable)
        selective_error = 1.0 - correct / i
        points.append((coverage, selective_error))
    return points


def subgroup_report(
    preds: Sequence[QueryPrediction],
    subgroup_key: str,
    *,
    metric: Callable[[Sequence[QueryPrediction]], float] = top_choice_utility,
) -> dict[str, dict[str, float]]:
    """Break ``metric`` and coverage out by the value of one subgroup key."""

    buckets: dict[str, list[QueryPrediction]] = {}
    for p in preds:
        value = p.subgroups.get(subgroup_key, "__unset__")
        buckets.setdefault(value, []).append(p)
    return {
        value: {
            "n": float(len(group)),
            "coverage": abstention_coverage(group),
            "metric": metric(group),
        }
        for value, group in sorted(buckets.items())
    }

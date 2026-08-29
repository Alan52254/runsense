"""Athlete-grouped forward-time evaluation splits with a gap.

Standard k-fold cross-validation is invalid for time-ordered data: it trains
on the future and tests on the past. These splits instead forward-chain along
a global integer time axis, and additionally guarantee the per-athlete
property that no later observation from an athlete ever sits in a training
fold that is evaluated against an earlier observation from any athlete.

A ``gap`` (in ``time_index`` units) widens the buffer between the last train
time and the first test time to blunt residual temporal autocorrelation.

Candidates shown together for one decision share a ``query_id`` and a
``time_index``; splits always keep a whole decision on one side.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ml.feature_contract import FeatureRow


class LeakageError(AssertionError):
    """Raised when a split violates a forward-time or grouping guarantee."""


@dataclass(frozen=True)
class ForwardTimeSplit:
    fold_index: int
    train_time_max: int
    test_time_min: int
    test_time_max: int
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]

    @property
    def gap_actual(self) -> int:
        return self.test_time_min - self.train_time_max


def _distinct_sorted_times(rows: Sequence[FeatureRow]) -> list[int]:
    return sorted({r.time_index for r in rows})


def athlete_grouped_forward_splits(
    rows: Sequence[FeatureRow],
    *,
    n_splits: int = 4,
    gap: int = 1,
    min_train_times: int = 1,
    require_group_history: bool = True,
) -> list[ForwardTimeSplit]:
    """Build up to ``n_splits`` expanding-window forward splits.

    The distinct ``time_index`` values are cut into ``n_splits + 1`` roughly
    equal contiguous blocks. Fold ``k`` trains on blocks ``0..k`` and tests on
    block ``k + 1`` minus any test time within ``gap`` of the train boundary.

    When ``require_group_history`` is set (the default), a test row is dropped
    unless that athlete already appears in the fold's training rows -- a
    brand-new athlete is a cold-start case for the deterministic fallback, not
    a learned-ranker evaluation case.
    """

    if n_splits < 1:
        raise ValueError("n_splits must be >= 1")
    if gap < 0:
        raise ValueError("gap must be >= 0")

    times = _distinct_sorted_times(rows)
    if len(times) < n_splits + 1:
        raise ValueError(
            f"need at least {n_splits + 1} distinct time_index values, got {len(times)}"
        )

    n_blocks = n_splits + 1
    block_bounds: list[list[int]] = []
    for b in range(n_blocks):
        lo = (b * len(times)) // n_blocks
        hi = ((b + 1) * len(times)) // n_blocks
        block_bounds.append(times[lo:hi])

    splits: list[ForwardTimeSplit] = []
    for k in range(n_splits):
        train_times = {t for block in block_bounds[: k + 1] for t in block}
        if len(train_times) < min_train_times:
            continue
        train_time_max = max(train_times)
        test_block = block_bounds[k + 1]
        test_times = {t for t in test_block if t > train_time_max + gap}
        if not test_times:
            continue

        train_idx = [i for i, r in enumerate(rows) if r.time_index in train_times]
        train_groups = {rows[i].group for i in train_idx}
        test_idx = [
            i
            for i, r in enumerate(rows)
            if r.time_index in test_times
            and (not require_group_history or r.group in train_groups)
        ]
        if not train_idx or not test_idx:
            continue

        test_time_values = [rows[i].time_index for i in test_idx]
        splits.append(
            ForwardTimeSplit(
                fold_index=k,
                train_time_max=train_time_max,
                test_time_min=min(test_time_values),
                test_time_max=max(test_time_values),
                train_indices=tuple(train_idx),
                test_indices=tuple(test_idx),
            )
        )

    if not splits:
        raise ValueError("no non-empty forward splits could be constructed")
    return splits


def assert_forward_time(
    rows: Sequence[FeatureRow], split: ForwardTimeSplit, *, gap: int = 0
) -> None:
    """Raise :class:`LeakageError` if ``split`` leaks the future into training."""

    train_times = [rows[i].time_index for i in split.train_indices]
    test_times = [rows[i].time_index for i in split.test_indices]
    if not train_times or not test_times:
        raise LeakageError("split has an empty side")

    if min(test_times) <= max(train_times) + gap:
        raise LeakageError(
            f"global leak: max train time {max(train_times)} + gap {gap} "
            f">= min test time {min(test_times)}"
        )

    train_by_group: dict[int, int] = {}
    for i in split.train_indices:
        g = rows[i].group
        train_by_group[g] = max(train_by_group.get(g, -1), rows[i].time_index)
    for i in split.test_indices:
        r = rows[i]
        if r.group in train_by_group and r.time_index <= train_by_group[r.group]:
            raise LeakageError(
                f"per-athlete leak: group {r.group} trains on time "
                f"{train_by_group[r.group]} but is tested at earlier/equal time "
                f"{r.time_index}"
            )

    train_queries = {rows[i].query_id for i in split.train_indices}
    test_queries = {rows[i].query_id for i in split.test_indices}
    shared = train_queries & test_queries
    if shared:
        raise LeakageError(f"decision(s) {sorted(shared)} straddle the split")


def summarize_splits(
    rows: Sequence[FeatureRow], splits: Sequence[ForwardTimeSplit]
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for s in splits:
        out.append(
            {
                "fold_index": s.fold_index,
                "n_train": len(s.train_indices),
                "n_test": len(s.test_indices),
                "train_time_max": s.train_time_max,
                "test_time_min": s.test_time_min,
                "test_time_max": s.test_time_max,
                "gap_actual": s.gap_actual,
                "train_groups": sorted({rows[i].group for i in s.train_indices}),
                "test_groups": sorted({rows[i].group for i in s.test_indices}),
            }
        )
    return out

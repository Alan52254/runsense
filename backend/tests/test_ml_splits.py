"""Athlete-grouped forward-time splits with a gap."""

from __future__ import annotations

import pytest

from ml.feature_contract import FeatureRow
from ml.splits import (
    LeakageError,
    assert_forward_time,
    athlete_grouped_forward_splits,
    summarize_splits,
)
from ml.synthetic import SyntheticConfig, generate_synthetic_observations


def _rows(**kw):
    return generate_synthetic_observations(SyntheticConfig(seed=1, **kw))


def test_splits_are_forward_in_global_time_with_gap():
    rows = _rows()
    gap = 2
    splits = athlete_grouped_forward_splits(rows, n_splits=4, gap=gap)
    assert splits
    for s in splits:
        train_t = [rows[i].time_index for i in s.train_indices]
        test_t = [rows[i].time_index for i in s.test_indices]
        assert min(test_t) > max(train_t) + gap
        assert_forward_time(rows, s, gap=gap)


def test_no_later_train_obs_before_earlier_test_obs_per_athlete():
    rows = _rows()
    for s in athlete_grouped_forward_splits(rows, n_splits=3, gap=1):
        train_max_by_group: dict[int, int] = {}
        for i in s.train_indices:
            g = rows[i].group
            train_max_by_group[g] = max(train_max_by_group.get(g, -1), rows[i].time_index)
        for i in s.test_indices:
            r = rows[i]
            if r.group in train_max_by_group:
                assert r.time_index > train_max_by_group[r.group]


def test_training_window_expands():
    rows = _rows()
    splits = athlete_grouped_forward_splits(rows, n_splits=4, gap=0)
    sizes = [len(s.train_indices) for s in splits]
    assert sizes == sorted(sizes)
    assert sizes[0] < sizes[-1]


def test_decisions_never_straddle_a_split():
    rows = _rows()
    for s in athlete_grouped_forward_splits(rows, n_splits=4, gap=2):
        train_q = {rows[i].query_id for i in s.train_indices}
        test_q = {rows[i].query_id for i in s.test_indices}
        assert train_q.isdisjoint(test_q)


def test_assert_forward_time_detects_injected_leak():
    rows = _rows()
    splits = athlete_grouped_forward_splits(rows, n_splits=4, gap=2)
    s = splits[0]
    # Force a test index whose time is <= a training time for the same athlete.
    leaked = s.__class__(
        fold_index=s.fold_index,
        train_time_max=s.train_time_max,
        test_time_min=s.test_time_min,
        test_time_max=s.test_time_max,
        train_indices=s.train_indices,
        test_indices=s.train_indices[:1],
    )
    with pytest.raises(LeakageError):
        assert_forward_time(rows, leaked, gap=2)


def test_require_group_history_excludes_brand_new_athletes():
    rows = _rows()
    splits = athlete_grouped_forward_splits(
        rows, n_splits=4, gap=1, require_group_history=True
    )
    for s in splits:
        train_groups = {rows[i].group for i in s.train_indices}
        test_groups = {rows[i].group for i in s.test_indices}
        assert test_groups <= train_groups


def test_too_few_time_points_raises():
    rows = [
        FeatureRow(0, t, t, f"c{t}", t % 2, {"acute_load": 1.0})
        for t in range(3)
    ]
    with pytest.raises(ValueError):
        athlete_grouped_forward_splits(rows, n_splits=4, gap=0)


def test_summarize_splits_shape():
    rows = _rows()
    splits = athlete_grouped_forward_splits(rows, n_splits=3, gap=1)
    summary = summarize_splits(rows, splits)
    assert len(summary) == len(splits)
    assert {"fold_index", "n_train", "n_test", "gap_actual"} <= set(summary[0])

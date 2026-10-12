"""Platt scaling and calibration error."""

from __future__ import annotations

import math
import random

import pytest

from ml.calibration import (
    IdentityCalibrator,
    PlattCalibrator,
    brier_score,
    expected_calibration_error,
    reliability_table,
)


def _miscalibrated(n=600, seed=0):
    """Scores that are far too confident: true rate ~ sigmoid, score ~ score**3."""

    rng = random.Random(seed)
    raw_scores, labels = [], []
    for _ in range(n):
        true_p = rng.random()
        label = 1 if rng.random() < true_p else 0
        # Overconfident transform pushed toward 0/1.
        s = true_p**3 if true_p < 0.5 else 1 - (1 - true_p) ** 3
        raw_scores.append(s)
        labels.append(label)
    return raw_scores, labels


def test_ece_is_a_probability():
    scores, labels = _miscalibrated()
    ece = expected_calibration_error(scores, labels)
    assert 0.0 <= ece <= 1.0


def test_platt_reduces_calibration_error():
    scores, labels = _miscalibrated()
    before = expected_calibration_error(scores, labels)
    cal = PlattCalibrator().fit(scores, labels)
    after = expected_calibration_error(cal.transform(scores), labels)
    assert after < before


def test_platt_transform_is_monotonic():
    scores, labels = _miscalibrated()
    cal = PlattCalibrator().fit(scores, labels)
    xs = [i / 50 for i in range(51)]
    ys = cal.transform(xs)
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:]))
    assert all(0.0 <= y <= 1.0 for y in ys)


def test_identity_calibrator_clips_only():
    cal = IdentityCalibrator()
    assert cal.transform([-0.2, 0.5, 1.4]) == [0.0, 0.5, 1.0]


def test_brier_score_bounds():
    scores, labels = _miscalibrated()
    b = brier_score(scores, labels)
    assert 0.0 <= b <= 1.0


def test_reliability_table_weights_sum_to_one():
    scores, labels = _miscalibrated()
    table = reliability_table(scores, labels, n_bins=10)
    assert math.isclose(sum(row["weight"] for row in table), 1.0, rel_tol=1e-9)


def test_empty_inputs_raise():
    with pytest.raises(ValueError):
        expected_calibration_error([], [])
    with pytest.raises(RuntimeError):
        PlattCalibrator().transform([0.5])

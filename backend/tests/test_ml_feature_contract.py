"""Feature-contract determinism and de-identification."""

from __future__ import annotations

import math

import pytest

from ml.feature_contract import (
    DISALLOWED_FEATURE_KEYS,
    FEATURE_CONTRACT,
    RESERVED_ROW_KEYS,
    DeidentificationError,
    FeatureRow,
    assert_deidentified,
    feature_names,
    validate_features,
    validate_row,
    vectorize,
)


def _full_features() -> dict[str, float]:
    return {s.name: (s.minimum + s.maximum) / 2 for s in FEATURE_CONTRACT}


def test_contract_is_ordered_and_unique():
    names = feature_names()
    assert len(names) == len(set(names))
    assert names == tuple(s.name for s in FEATURE_CONTRACT)


def test_reserved_and_disallowed_keys_are_not_features():
    names = set(feature_names())
    assert names.isdisjoint(RESERVED_ROW_KEYS)
    assert names.isdisjoint(DISALLOWED_FEATURE_KEYS)
    # group / time_index are structural, never model inputs.
    assert "group" not in names and "time_index" not in names


def test_vectorize_is_deterministic_and_ordered():
    feats = _full_features()
    v1 = vectorize(feats)
    v2 = vectorize(dict(reversed(list(feats.items()))))
    assert v1 == v2
    assert len(v1) == len(FEATURE_CONTRACT)


def test_missing_values_fall_back_to_defaults():
    v = vectorize({})
    for value, spec in zip(v, FEATURE_CONTRACT):
        assert value == pytest.approx(spec.default)


def test_out_of_range_and_non_finite_are_handled():
    v = vectorize({"acute_load": 10_000.0, "temp_c": float("nan"), "sleep_hours": -5.0})
    idx = {s.name: i for i, s in enumerate(FEATURE_CONTRACT)}
    assert v[idx["acute_load"]] == 4000.0
    assert v[idx["temp_c"]] == 15.0  # nan -> default
    assert v[idx["sleep_hours"]] == 0.0  # clamped to minimum
    assert all(math.isfinite(x) for x in v)


def test_binary_features_snap():
    idx = {s.name: i for i, s in enumerate(FEATURE_CONTRACT)}
    assert vectorize({"weather_actionable": 0.9})[idx["weather_actionable"]] == 1.0
    assert vectorize({"weather_actionable": 0.2})[idx["weather_actionable"]] == 0.0


@pytest.mark.parametrize("bad_key", ["athlete_id", "email", "local_training_date", "city", "notes"])
def test_identifying_keys_are_rejected(bad_key):
    with pytest.raises(DeidentificationError):
        validate_features({bad_key: 1})


def test_unknown_key_rejected():
    with pytest.raises(DeidentificationError):
        validate_features({"vo2max_secret": 55.0})


def test_non_numeric_feature_rejected():
    with pytest.raises(DeidentificationError):
        validate_features({"acute_load": "high"})


def test_assert_deidentified_checks_surrogates():
    good = FeatureRow(2, 5, 7, "cand-1", 1, _full_features())
    assert_deidentified(good)
    validate_row(good)

    with pytest.raises(DeidentificationError):
        assert_deidentified(FeatureRow(-1, 0, 0, "c", 0, {}))
    with pytest.raises(DeidentificationError):
        assert_deidentified(FeatureRow(0, 0, 0, "", 0, {}))


def test_validate_row_rejects_bad_label():
    with pytest.raises(ValueError):
        validate_row(FeatureRow(0, 0, 0, "c", 2, _full_features()))

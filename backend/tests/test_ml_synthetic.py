"""Synthetic fixtures are deterministic and de-identified."""

from __future__ import annotations

from ml.feature_contract import (
    DISALLOWED_FEATURE_KEYS,
    feature_names,
    validate_row,
)
from ml.synthetic import (
    SyntheticConfig,
    generate_synthetic_observations,
    records_to_rows,
    rows_to_records,
)


def test_generation_is_deterministic_for_a_seed():
    a = rows_to_records(generate_synthetic_observations(SyntheticConfig(seed=7)))
    b = rows_to_records(generate_synthetic_observations(SyntheticConfig(seed=7)))
    assert a == b


def test_different_seed_changes_data():
    a = rows_to_records(generate_synthetic_observations(SyntheticConfig(seed=1)))
    b = rows_to_records(generate_synthetic_observations(SyntheticConfig(seed=2)))
    assert a != b


def test_rows_are_deidentified_and_contract_complete():
    rows = generate_synthetic_observations(SyntheticConfig(seed=0))
    names = set(feature_names())
    for r in rows:
        validate_row(r)
        assert set(r.features) == names
        assert DISALLOWED_FEATURE_KEYS.isdisjoint(r.features)
        assert isinstance(r.group, int) and isinstance(r.time_index, int)


def test_time_index_is_monotonic_per_group():
    rows = generate_synthetic_observations(SyntheticConfig(seed=0))
    seen: dict[int, int] = {}
    for r in rows:
        assert r.time_index >= seen.get(r.group, -1)
        seen[r.group] = r.time_index


def test_exactly_one_accepted_candidate_per_decision():
    rows = generate_synthetic_observations(SyntheticConfig(seed=0))
    by_query: dict[int, list[int]] = {}
    for r in rows:
        by_query.setdefault(r.query_id, []).append(r.label)
    for labels in by_query.values():
        assert sum(labels) == 1
        assert len(labels) >= 2


def test_cold_start_athletes_have_short_history():
    cfg = SyntheticConfig(seed=0, cold_start_athletes=2, cold_start_days=4, days_per_athlete=40)
    rows = generate_synthetic_observations(cfg)
    per_group_days = {}
    for r in rows:
        per_group_days.setdefault(r.group, set()).add(r.time_index)
    assert len(per_group_days[0]) == 4
    assert len(per_group_days[1]) == 4
    assert len(per_group_days[2]) == 40


def test_triage_escalations_accept_the_rest_option():
    rows = generate_synthetic_observations(SyntheticConfig(seed=0))
    by_query: dict[int, list] = {}
    for r in rows:
        by_query.setdefault(r.query_id, []).append(r)
    saw_escalation = False
    for cand in by_query.values():
        if cand[0].features["triage_escalated"] >= 0.5:
            saw_escalation = True
            accepted = next(r for r in cand if r.label == 1)
            assert accepted.features["candidate_intensity_ord"] == 0.0
    assert saw_escalation


def test_round_trip_records():
    rows = generate_synthetic_observations(SyntheticConfig(seed=3))
    assert rows_to_records(records_to_rows(rows_to_records(rows))) == rows_to_records(rows)

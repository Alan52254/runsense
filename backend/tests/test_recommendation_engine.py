"""Pure unit tests -- no DB needed. See tasks.md 4.3/4.4."""

from __future__ import annotations

import ast
from pathlib import Path

from app.recommendation_engine import compute_emotional_context, compute_recommendation


def test_insufficient_data_quality_wins_regardless_of_ratio():
    rec = compute_recommendation(load_ratio=0.5, data_quality="INSUFFICIENT")
    assert rec.adjustment_reason_code == "INSUFFICIENT_DATA"

    rec_low = compute_recommendation(load_ratio=2.0, data_quality="LOW")
    assert rec_low.adjustment_reason_code == "INSUFFICIENT_DATA"


def test_elevated_load_ratio_recommends_reduced_intensity():
    rec = compute_recommendation(load_ratio=1.5, data_quality="SUFFICIENT")
    assert rec.adjustment_reason_code == "RECENT_LOAD_ELEVATED"
    assert rec.duration_minutes == 30


def test_reduced_load_ratio_recommends_a_build_session():
    rec = compute_recommendation(load_ratio=0.5, data_quality="SUFFICIENT")
    assert rec.adjustment_reason_code == "RECENT_LOAD_REDUCED"


def test_steady_load_ratio_is_the_default():
    rec = compute_recommendation(load_ratio=1.0, data_quality="SUFFICIENT")
    assert rec.adjustment_reason_code == "STEADY_STATE"


def test_null_load_ratio_with_sufficient_quality_is_steady_state():
    # data_quality=SUFFICIENT with load_ratio=None shouldn't happen in
    # practice (SUFFICIENT implies a computable ratio), but the function
    # must not crash on it -- falls through to the STEADY_STATE default.
    rec = compute_recommendation(load_ratio=None, data_quality="SUFFICIENT")
    assert rec.adjustment_reason_code == "STEADY_STATE"


def test_distance_and_pace_are_derived_from_segments_not_left_null():
    """Regression test: distance_km/target_pace_sec_per_km used to be
    hardcoded None in every branch, leaving the dashboard's 預計距離/目標配速
    tiles permanently blank even though the segments carried enough detail
    (distance, duration, pace range) to compute both."""
    rec = compute_recommendation(load_ratio=1.5, data_quality="SUFFICIENT")  # easy_segments
    assert rec.distance_km is not None and rec.distance_km > 0
    assert rec.target_pace_sec_per_km is not None


def test_distance_km_sums_across_segments_including_duration_only_ones():
    # easy_segments: warmup 1000m + main (1200s @ midpoint 360s/km -> 3.33km)
    # + cooldown 1000m = 5.33km, rounded to 1 decimal.
    rec = compute_recommendation(load_ratio=1.5, data_quality="SUFFICIENT")
    assert rec.distance_km == 5.3


def test_target_pace_is_the_work_segments_midpoint_not_a_blend():
    # tempo_segments' work segment: target_pace_range_sec_per_km=[240, 270]
    # -> midpoint 255, not diluted by the easier warmup/cooldown paces.
    rec = compute_recommendation(load_ratio=0.5, data_quality="SUFFICIENT")
    assert rec.target_pace_sec_per_km == 255
    assert rec.distance_km == 8.7


def test_emotional_context_rising_falling_stable():
    assert compute_emotional_context("X", acute_load=200, chronic_load=100).load_trend_direction == "RISING"
    assert compute_emotional_context("X", acute_load=50, chronic_load=100).load_trend_direction == "FALLING"
    assert compute_emotional_context("X", acute_load=100, chronic_load=100).load_trend_direction == "STABLE"
    assert compute_emotional_context("X", acute_load=0, chronic_load=0).load_trend_direction == "STABLE"


def test_recommendation_engine_never_imports_the_llm_client():
    """Structural guarantee for REQ-AI-004, not just a convention: this
    module's source has no reference to app.llm_client anywhere, so there
    is no code path by which an LLM response could reach a prescription
    field, regardless of what future changes do to this file's logic."""
    source = Path(__file__).parent.parent.joinpath("app", "recommendation_engine.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("llm_client" in name for name in imported_modules)

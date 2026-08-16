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

"""Deterministic training recommendation. REQ-AI-004: every prescription
field here is server-rendered and never touched by the LLM -- this module
has no import of app.llm_client anywhere in its call graph, which is a
structural guarantee, not just a convention (see tasks.md 4.4).

design.md Decision 5: a small rule table over load_ratio/data_quality, not
a new training-science model. The SRS specifies the architectural isolation
(REQ-AI-003/004), not a specific periodization algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass

ALGORITHM_VERSION = "guidance-rule-2026.08.1"


@dataclass(frozen=True)
class Recommendation:
    workout_type: str
    duration_minutes: int
    distance_km: float | None
    target_pace_sec_per_km: int | None
    intensity_label: str
    adjustment_reason_code: str
    algorithm_version: str


@dataclass(frozen=True)
class EmotionalContext:
    adjustment_reason_code: str
    load_trend_direction: str  # "RISING" | "FALLING" | "STABLE"


def compute_recommendation(load_ratio: float | None, data_quality: str) -> Recommendation:
    if data_quality in ("LOW", "INSUFFICIENT"):
        return Recommendation(
            workout_type="輕鬆有氧跑",
            duration_minutes=30,
            distance_km=None,
            target_pace_sec_per_km=None,
            intensity_label="RPE 3-4",
            adjustment_reason_code="INSUFFICIENT_DATA",
            algorithm_version=ALGORITHM_VERSION,
        )
    if load_ratio is not None and load_ratio > 1.3:
        return Recommendation(
            workout_type="輕鬆有氧跑",
            duration_minutes=30,
            distance_km=None,
            target_pace_sec_per_km=None,
            intensity_label="RPE 3-4",
            adjustment_reason_code="RECENT_LOAD_ELEVATED",
            algorithm_version=ALGORITHM_VERSION,
        )
    if load_ratio is not None and load_ratio < 0.8:
        return Recommendation(
            workout_type="節奏跑",
            duration_minutes=45,
            distance_km=None,
            target_pace_sec_per_km=None,
            intensity_label="RPE 6-7",
            adjustment_reason_code="RECENT_LOAD_REDUCED",
            algorithm_version=ALGORITHM_VERSION,
        )
    return Recommendation(
        workout_type="輕鬆有氧跑",
        duration_minutes=40,
        distance_km=None,
        target_pace_sec_per_km=None,
        intensity_label="RPE 4-5",
        adjustment_reason_code="STEADY_STATE",
        algorithm_version=ALGORITHM_VERSION,
    )


def compute_emotional_context(
    adjustment_reason_code: str, acute_load: float, chronic_load: float
) -> EmotionalContext:
    if chronic_load == 0:
        direction = "STABLE"
    elif acute_load > chronic_load * 1.1:
        direction = "RISING"
    elif acute_load < chronic_load * 0.9:
        direction = "FALLING"
    else:
        direction = "STABLE"
    return EmotionalContext(
        adjustment_reason_code=adjustment_reason_code, load_trend_direction=direction
    )

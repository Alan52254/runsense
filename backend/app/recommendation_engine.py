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
    segments: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class EmotionalContext:
    adjustment_reason_code: str
    load_trend_direction: str  # "RISING" | "FALLING" | "STABLE"


def _segment_distance_km(segment: dict[str, object]) -> float:
    """A segment's own distance, or -- for a duration-only segment like the
    tempo/easy "main" block above, which specifies effort by time, not
    distance -- distance backed out from duration x its pace range's
    midpoint. Never both fields at once in this module's own segment data,
    so there's no ambiguity about which one wins."""
    distance_meters = segment.get("distance_meters")
    if isinstance(distance_meters, int | float):
        return distance_meters / 1000
    duration_seconds = segment.get("duration_seconds")
    pace_range = segment.get("target_pace_range_sec_per_km")
    if isinstance(duration_seconds, int | float) and isinstance(pace_range, list) and len(pace_range) == 2:
        midpoint_pace = (pace_range[0] + pace_range[1]) / 2
        return duration_seconds / midpoint_pace
    return 0.0


def _total_distance_km(segments: tuple[dict[str, object], ...]) -> float:
    return round(sum(_segment_distance_km(s) for s in segments), 1)


def _work_segment_pace_sec_per_km(segments: tuple[dict[str, object], ...]) -> int | None:
    """The "work" segment's own pace-range midpoint -- the main effort's
    target, not a distance-weighted blend across warmup/main/cooldown,
    which would understate how hard the main effort actually is (matching
    DashboardScreen.tsx's mainEffortSegment convention on the frontend)."""
    for segment in segments:
        if segment.get("kind") != "work":
            continue
        pace_range = segment.get("target_pace_range_sec_per_km")
        if isinstance(pace_range, list) and len(pace_range) == 2:
            return round((pace_range[0] + pace_range[1]) / 2)
    return None


def compute_recommendation(load_ratio: float | None, data_quality: str) -> Recommendation:
    easy_segments = (
        {"id": "warmup", "kind": "warmup", "label": "熱身慢跑", "distance_meters": 1000, "target_pace_range_sec_per_km": [330, 390]},
        {"id": "main", "kind": "work", "label": "輕鬆有氧跑", "duration_seconds": 1200, "target_pace_range_sec_per_km": [330, 390]},
        {"id": "cooldown", "kind": "cooldown", "label": "收操慢跑", "distance_meters": 1000, "target_pace_range_sec_per_km": [360, 420]},
    )
    tempo_segments = (
        {"id": "warmup", "kind": "warmup", "label": "熱身慢跑", "distance_meters": 2000, "target_pace_range_sec_per_km": [300, 360]},
        {"id": "main", "kind": "work", "label": "節奏跑", "duration_seconds": 1200, "target_pace_range_sec_per_km": [240, 270]},
        {"id": "cooldown", "kind": "cooldown", "label": "收操慢跑", "distance_meters": 2000, "target_pace_range_sec_per_km": [330, 390]},
    )
    if data_quality in ("LOW", "INSUFFICIENT"):
        return Recommendation(
            workout_type="輕鬆有氧跑",
            duration_minutes=30,
            distance_km=_total_distance_km(easy_segments),
            target_pace_sec_per_km=_work_segment_pace_sec_per_km(easy_segments),
            intensity_label="RPE 3-4",
            adjustment_reason_code="INSUFFICIENT_DATA",
            algorithm_version=ALGORITHM_VERSION,
            segments=easy_segments,
        )
    if load_ratio is not None and load_ratio > 1.3:
        return Recommendation(
            workout_type="輕鬆有氧跑",
            duration_minutes=30,
            distance_km=_total_distance_km(easy_segments),
            target_pace_sec_per_km=_work_segment_pace_sec_per_km(easy_segments),
            intensity_label="RPE 3-4",
            adjustment_reason_code="RECENT_LOAD_ELEVATED",
            algorithm_version=ALGORITHM_VERSION,
            segments=easy_segments,
        )
    if load_ratio is not None and load_ratio < 0.8:
        return Recommendation(
            workout_type="節奏跑",
            duration_minutes=45,
            distance_km=_total_distance_km(tempo_segments),
            target_pace_sec_per_km=_work_segment_pace_sec_per_km(tempo_segments),
            intensity_label="RPE 6-7",
            adjustment_reason_code="RECENT_LOAD_REDUCED",
            algorithm_version=ALGORITHM_VERSION,
            segments=tempo_segments,
        )
    return Recommendation(
        workout_type="輕鬆有氧跑",
        duration_minutes=40,
        distance_km=_total_distance_km(easy_segments),
        target_pace_sec_per_km=_work_segment_pace_sec_per_km(easy_segments),
        intensity_label="RPE 4-5",
        adjustment_reason_code="STEADY_STATE",
        algorithm_version=ALGORITHM_VERSION,
        segments=easy_segments,
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

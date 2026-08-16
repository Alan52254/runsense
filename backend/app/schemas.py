from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class CreateActivityRequest(BaseModel):
    """POST /activities request body.

    No athlete_id, no athlete_timezone: both are server-derived
    (see design.md Decisions 1 and 5 / 10). Unknown fields are rejected
    rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    client_mutation_id: uuid.UUID
    duration_minutes: float = Field(gt=0, allow_inf_nan=False)
    rpe: int = Field(ge=1, le=10)
    performed_at: datetime

    @field_validator("performed_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("performed_at must include timezone information")
        return value.astimezone(timezone.utc)


class ActivityResponse(BaseModel):
    id: uuid.UUID
    athlete_id: uuid.UUID
    client_mutation_id: uuid.UUID
    provider: str
    provider_activity_id: str | None
    duration_minutes: float
    rpe: int
    performed_at: datetime
    timezone_snapshot: str
    local_training_date: date
    session_load: float
    unit: str
    source_metric: str
    server_version: int
    created_at: datetime


class ActivityHistoryResponse(BaseModel):
    items: list[ActivityResponse]
    next_cursor: str | None = None


class RestDayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: StrictBool


class RestDayResponse(BaseModel):
    date: date
    confirmed: bool


class TrainingLoadPointResponse(BaseModel):
    date: date
    session_load: float
    acute_load: float
    chronic_load: float
    load_ratio: float | None
    data_quality: str
    observation_days: int
    algorithm_version: str
    schema_version: int
    computed_at: datetime
    input_snapshot_hash: str


class TrainingLoadSeriesResponse(BaseModel):
    unit: str
    source_metric: str
    points: list[TrainingLoadPointResponse]


class TrainingLoadTrendResponse(BaseModel):
    start_date: date
    end_date: date
    series: list[TrainingLoadSeriesResponse]


class UpdateProfileRequest(BaseModel):
    """PATCH /profile request body. Both fields optional and independent —
    at least one must be present (see EmptyProfileUpdateError)."""

    model_config = ConfigDict(extra="forbid")

    city: str | None = None
    timezone: str | None = None


class ProfileResponse(BaseModel):
    city: str | None
    timezone: str


class WeatherResponse(BaseModel):
    state: str  # "LIVE" | "CACHED" | "STALE" | "UNAVAILABLE"
    city: str | None
    temperature_c: float | None
    humidity_pct: float | None
    observed_at: datetime | None
    pace_adjustment_sec_per_km: int | None


class RecommendationResponse(BaseModel):
    workout_type: str
    duration_minutes: int
    distance_km: float | None
    target_pace_sec_per_km: int | None
    intensity_label: str
    adjustment_reason_code: str
    algorithm_version: str


class GuidanceResponse(BaseModel):
    local_date: date
    recommendation: RecommendationResponse
    tone_variant_id: str
    tone_text: str
    tone_reviewed_by: str
    computed_at: datetime

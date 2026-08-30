from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


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
    # Optional: the manual-log form has always collected this, but there was
    # nowhere for it to go before this field existed -- it was silently
    # dropped. Universal (unlike device_metrics below) since a manually
    # logged run can have a known distance same as a device-recorded one.
    distance_km: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Optional block-by-block detail (warmup/interval/cooldown/recovery/jog),
    # same untyped passthrough shape as CreateAssignedWorkoutRequest.structure
    # -- purely additive: duration_minutes/rpe above still drive session_load
    # regardless of whether this is populated, so a plain quick log with no
    # structure stays exactly as valid as it always was.
    structure: list[dict[str, object]] = Field(default_factory=list, max_length=50)

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
    distance_km: float | None
    # Device-reported training metrics (heart rate, cadence, elevation,
    # calories, training effect...) with no universal column of their own --
    # untyped passthrough, empty for every manual entry. Read-only from this
    # API today: see backend/scripts/backfill_garmin_metrics.py, the only
    # writer.
    device_metrics: dict[str, object] = Field(default_factory=dict)
    structure: list[dict[str, object]] = Field(default_factory=list)


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
    """PATCH /profile request body. All fields optional and independent —
    at least one must be present (see EmptyProfileUpdateError)."""

    model_config = ConfigDict(extra="forbid")

    city: str | None = None
    timezone: str | None = None
    # "male" | "female" | None. Only two values because that's what the
    # weather-pace research (see app/weather_pace.py) reports separate
    # curves for; None means "not set", not a third category.
    sex: Literal["male", "female"] | None = None


class ProfileResponse(BaseModel):
    city: str | None
    timezone: str
    sex: Literal["male", "female"] | None


class TimeOfDayTemperatureEstimate(BaseModel):
    label: Literal["morning", "midday", "evening"]
    hour: int
    temperature_c: float
    # This slot's estimated temperature vs. WeatherResponse's
    # climate_normal_reference_c (the SAME fixed evening reference used for
    # every slot and for the "now" figure) -- so slots are directly
    # comparable to each other and to speed_loss_pct_relative_to_normal:
    # a bigger number here means "actually running at this hour costs more
    # than the pace assumes", not "this hour is unusual for itself".
    speed_loss_pct: float


class SegmentTemperatureEstimate(BaseModel):
    # Minutes from "now" this segment is estimated to start -- echoed back
    # from the request so a client can match each estimate back to the
    # segment it asked about without needing to keep its own ordering
    # assumptions in sync with the response.
    offset_min: float
    temperature_c: float
    # Same meaning as TimeOfDayTemperatureEstimate.speed_loss_pct: compared
    # against the SAME fixed climate_normal_reference_c (early evening),
    # not this offset's own hour, so segments are directly comparable to
    # each other and to speed_loss_pct_relative_to_normal.
    speed_loss_pct: float


class WeatherResponse(BaseModel):
    state: str  # "LIVE" | "CACHED" | "STALE" | "UNAVAILABLE"
    city: str | None
    temperature_c: float | None
    humidity_pct: float | None
    observed_at: datetime | None
    # % of running speed lost right now -- the El Helou et al. (2012, Table
    # S3) sex-specific curve (relative to the paper's own ~6-10C absolute
    # physiological optimum), then scaled by app/weather_pace.py's
    # acclimatization_multiplier. Kept for transparency/explainability, but
    # UIs should prefer speed_loss_pct_relative_to_normal as the headline
    # figure -- this absolute curve reads as a large %% on essentially any
    # day in a warm city, since such cities are rarely near the paper's
    # optimum, which makes it a poor "is today unusual?" signal. null
    # whenever temperature_c is null.
    speed_loss_pct: float | None
    # The El Helou curve's own output, before acclimatization scaling --
    # kept alongside the adjusted figure for transparency/explainability,
    # not just as an internal step. null under the same conditions as above.
    speed_loss_pct_unadjusted: float | None
    # The same curve read at two points and subtracted: speed_loss_pct at
    # temperature_c minus speed_loss_pct at climate_normal_reference_c
    # (this city/month's typical temperature at the assumed reference run
    # hour -- early evening, see routes/weather.py's _REFERENCE_RUN_HOUR).
    # Unlike speed_loss_pct this can be negative (today is genuinely
    # cooler than a typical evening). The headline figure for both a
    # coach-set target pace and the app's own recommended pace, since both
    # are assumed calibrated for a typical evening run, not for the
    # paper's optimum (see weather_pace.py's
    # speed_loss_pct_relative_to_normal docstring for why applying
    # speed_loss_pct on top would double-count that). Falls back to
    # speed_loss_pct_unadjusted when city has no climate-normal entry,
    # same graceful-degradation as speed_loss_pct.
    speed_loss_pct_relative_to_normal: float | None
    # This month's climate-normal MEAN temperature for `city` (see
    # app/climate_normals.py) -- null when city isn't in that table, which
    # also means speed_loss_pct above falls back to the unadjusted figure
    # and time_of_day_estimates is empty. Informational only -- not what
    # speed_loss_pct_relative_to_normal is centered on; see
    # climate_normal_reference_c for that.
    climate_normal_temperature_c: float | None
    # What's climatologically typical for `city` at the assumed reference
    # run hour (early evening -- see routes/weather.py's
    # _REFERENCE_RUN_HOUR, from app/diurnal_temperature.py's diurnal model
    # applied to this month's normal low/high) -- the actual reference
    # speed_loss_pct_relative_to_normal, speed_loss_pct's acclimatization
    # scaling, and every time_of_day_estimates slot are centered on. This
    # is a FIXED hour regardless of what time it actually is right now --
    # see _REFERENCE_RUN_HOUR's comment for why. Falls back to
    # climate_normal_temperature_c (the flat monthly mean) when sunrise/
    # sunset data isn't available; null under the same conditions as
    # climate_normal_temperature_c.
    climate_normal_reference_c: float | None
    time_of_day_estimates: list[TimeOfDayTemperatureEstimate] = Field(default_factory=list)
    # One entry per requested `segment_offsets_min` query value (same order,
    # not deduplicated) -- lets a client ask "what will the temperature/pace
    # impact be `offset_min` minutes from now", e.g. for each block of a
    # multi-segment workout as it actually unfolds in time, rather than only
    # the three fixed time_of_day_estimates slots. Empty when no offsets were
    # requested, or under the same no-climate-normal/no-sun-time conditions
    # that empty time_of_day_estimates.
    segment_estimates: list[SegmentTemperatureEstimate] = Field(default_factory=list)


class WorkoutSegmentResponse(BaseModel):
    id: str
    kind: str
    label: str
    distance_meters: int | None = None
    duration_seconds: int | None = None
    repetitions: int | None = None
    target_pace_sec_per_km: int | None = None
    target_pace_range_sec_per_km: list[int] | None = None
    after_repetition: str | None = None


class RecommendationResponse(BaseModel):
    workout_type: str
    duration_minutes: int
    distance_km: float | None
    target_pace_sec_per_km: int | None
    intensity_label: str
    adjustment_reason_code: str
    algorithm_version: str
    segments: list[WorkoutSegmentResponse] = Field(default_factory=list)


class GuidanceResponse(BaseModel):
    local_date: date
    recommendation: RecommendationResponse
    tone_variant_id: str
    tone_text: str
    tone_reviewed_by: str
    computed_at: datetime


class TeamSummaryResponse(BaseModel):
    """One row of GET /teams/mine -- the teams the actor coaches."""

    team_id: uuid.UUID
    name: str
    role: str


class MyTeamsResponse(BaseModel):
    items: list[TeamSummaryResponse]


class CoachRosterRowResponse(BaseModel):
    """A query-time Coach Roster Row projection (CONTEXT.md). Every field
    below the membership basics (athlete_id/name/status/joined_at/
    granted_scopes) is null unless the athlete's currently granted Consent
    Scopes cover it -- never a stored copy, never masked-but-present."""

    team_id: uuid.UUID
    athlete_id: uuid.UUID
    name: str
    status: str
    joined_at: datetime | None
    granted_scopes: list[str]

    last_activity_local_date: date | None

    acute_load_au: float | None
    chronic_load_au: float | None
    load_ratio: float | None
    data_quality: str | None
    last_14_days_load: list[float]

    injury_has_issue: bool | None
    injury_severity_band: str | None
    injury_free_text: str | None


class TeamRosterResponse(BaseModel):
    team_id: uuid.UUID
    items: list[CoachRosterRowResponse]


ConsentScope = Literal["activity_summary", "training_load", "injury_status", "injury_detail"]


class TeamMembershipResponse(BaseModel):
    team_id: uuid.UUID
    team_name: str
    coach_name: str
    role: str
    status: str
    invited_at: datetime
    joined_at: datetime | None
    left_at: datetime | None


class TeamMembershipListResponse(BaseModel):
    items: list[TeamMembershipResponse]


class UpdateTeamMembershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "decline", "leave"]


class ConsentGrantResponse(BaseModel):
    team_id: uuid.UUID
    scope: ConsentScope
    granted: bool
    changed_at: datetime


class ConsentGrantListResponse(BaseModel):
    items: list[ConsentGrantResponse]


class UpdateConsentGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: uuid.UUID
    granted: StrictBool


class CreateInjuryReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_mutation_id: uuid.UUID
    has_issue: StrictBool
    severity_band: Literal["NONE", "MILD", "MODERATE", "SEVERE"]
    body_part: str | None = Field(default=None, max_length=80)
    free_text: str | None = Field(default=None, max_length=2000)
    reported_at: datetime

    @field_validator("reported_at")
    @classmethod
    def require_reported_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("reported_at must include timezone information")
        return value.astimezone(timezone.utc)

    @field_validator("body_part", "free_text")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def require_consistent_issue_fields(self):
        if not self.has_issue and (self.severity_band != "NONE" or self.body_part is not None):
            raise ValueError("no-issue reports require severity NONE and no body part")
        if self.has_issue and (self.severity_band == "NONE" or self.body_part is None):
            raise ValueError("issue reports require a severity and body part")
        return self


class InjuryReportResponse(BaseModel):
    id: uuid.UUID
    athlete_id: uuid.UUID
    client_mutation_id: uuid.UUID
    has_issue: bool
    severity_band: str
    body_part: str | None
    reported_at: datetime
    timezone_snapshot: str
    local_training_date: date
    free_text: str | None
    created_at: datetime


class InjuryReportListResponse(BaseModel):
    items: list[InjuryReportResponse]


# ---------------- Settings: Security/Privacy/Integration ----------------
# See backend/app/routes/settings.py and backend/README.md's Settings
# section. Demo-appropriate, not full compliance infrastructure.

class AuthSessionResponse(BaseModel):
    id: uuid.UUID
    device: str
    ip_masked: str
    location: str
    last_active_at: datetime
    is_current: bool


class AuthSessionListResponse(BaseModel):
    items: list[AuthSessionResponse]


class MfaVerifyRequest(BaseModel):
    """POST /me/settings/mfa/verify request body. `code` must equal the
    fixed demo code documented in web/README.md -- this is a lightweight
    MFA-satisfied toggle for demonstrating REQ-AUTH-007's gate, not a real
    TOTP/SMS integration."""

    model_config = ConfigDict(extra="forbid")

    code: str


class MfaVerifyResponse(BaseModel):
    mfa_satisfied: bool


class PrivacyExportResponse(BaseModel):
    """GET /me/settings/privacy/export. Reuses ActivityResponse and
    TrainingLoadPointResponse rather than inventing a parallel export shape
    -- the export is just the athlete's own already-readable data."""

    exported_at: datetime
    profile: ProfileResponse
    completed_activities: list[ActivityResponse]
    training_load_daily: list[TrainingLoadPointResponse]


class DeletionRequestResponse(BaseModel):
    deletion_requested_at: datetime


class GarminIntegrationResponse(BaseModel):
    """GET /me/settings/integrations/garmin. Reflects
    GARMIN_ACTIVITY_SYNC_ENABLED (REQ-GARMIN-001) -- no real Garmin OAuth."""

    enabled: bool
    reason: str


AuditEventType = Literal[
    "AUTH_LOGIN",
    "AUTH_FAILURE",
    "ROLE_CHANGE",
    "CONSENT_GRANT",
    "CONSENT_REVOKE",
    "DATA_EXPORT",
    "CROSS_TENANT_DENIED",
    "BILLING_CHANGE",
]


class AuditLogEntryResponse(BaseModel):
    id: uuid.UUID
    event: AuditEventType
    created_at: datetime
    summary: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogEntryResponse]


# ---------------- Coach Assignments (AssignedWorkout) ----------------
# See backend/app/routes/assignments.py and CONTEXT.md's Assigned Workout
# definition. No PATCH for MVP -- AssignmentsScreen.tsx has no
# mark-complete/missed interaction yet.

class CreateAssignedWorkoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    athlete_id: uuid.UUID
    local_date: date
    title: str = Field(min_length=1, max_length=200)
    duration_minutes: int = Field(gt=0, le=600)
    intensity_label: str = Field(min_length=1, max_length=80)
    structure: list[dict[str, object]] = Field(default_factory=list, max_length=50)


class AssignedWorkoutResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    athlete_id: uuid.UUID
    local_date: date
    title: str
    duration_minutes: int
    intensity_label: str
    status: Literal["SCHEDULED", "COMPLETED", "MISSED"]
    created_at: datetime
    structure: list[dict[str, object]] = Field(default_factory=list)


class AssignedWorkoutListResponse(BaseModel):
    items: list[AssignedWorkoutResponse]


class ScenarioOverrideRequest(BaseModel):
    """POST /training-plan/evaluate request body.

    A Scenario Override states *facts about the Athlete's situation*. There is
    deliberately no field here for distance, duration, pace, intensity, or
    workout type: ADR 0002 is enforced by their absence plus extra="forbid",
    so a caller -- including a language model -- attempting to prescribe a
    workout is rejected at the boundary rather than reviewed for.
    """

    model_config = ConfigDict(extra="forbid")

    local_date: date | None = None
    # Bounded to the range the published temperature-decay curve and the
    # interface both offer; outside it the answer would be extrapolation.
    temperature_c: float | None = Field(default=None, ge=-20, le=50, allow_inf_nan=False)
    humidity_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    # A fact about the Athlete's day, not a prescription: it filters which
    # reviewed candidates are eligible and never sets a candidate's duration.
    available_minutes: int | None = Field(default=None, ge=1, le=600)
    reported_body_part: str | None = Field(default=None, max_length=64)
    reported_severity_band: Literal["MILD", "MODERATE", "SEVERE"] | None = None
    label: str | None = Field(default=None, max_length=80)

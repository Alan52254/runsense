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


class AssignedWorkoutListResponse(BaseModel):
    items: list[AssignedWorkoutResponse]

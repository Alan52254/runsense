/* Domain types. Field names deliberately mirror the backend contract
 * (backend/app/routes/activities.py) and the SRS, so a reader can trace a
 * screen back to a REQ number without a translation layer. */

/** client/src/types.ts SyncState — same five states, same meanings. */
export type SyncState =
  | "LOCAL_ONLY"
  | "SYNCING"
  | "SYNCED"
  | "FAILED_RETRYABLE"
  | "FAILED_TERMINAL";

/** REQ-LOAD-001: two units that must never be added together. */
export type LoadUnit = "AU" | "garmin_epoc";

/** REQ-LOAD-001: "SESSION_RPE", never "trimp_srpe" (retired name). */
export type SourceMetric = "SESSION_RPE" | "GARMIN_DEVICE_LOAD";

/** REQ-LOAD-005 / REQ-LOAD-006 / REQ-RISK-001. */
export type DataQuality = "OK" | "LOW" | "INSUFFICIENT";

export type ActivityProvider = "manual" | "garmin";

export interface Activity {
  id: string;
  clientMutationId: string;
  provider: ActivityProvider;
  /** REQ-DEDUP-001: UNIQUE is (provider, provider_activity_id), not the id alone. */
  providerActivityId: string | null;
  performedAtUtc: string;
  /** REQ-TZ-001: derived from UTC + the athlete's timezone, never server-local. */
  localTrainingDate: string;
  timezoneSnapshot: string;
  durationMinutes: number;
  /** null for device-sourced records, which carry no session-RPE. */
  rpe: number | null;
  distanceKm: number | null;
  sessionLoad: number;
  unit: LoadUnit;
  sourceMetric: SourceMetric;
  note: string;
  syncState: SyncState;
  syncAttempts: number;
  lastErrorCode: string | null;
  serverVersion: number | null;
  /** REQ-DEDUP-002: flagged only — never auto-merged or auto-deleted. */
  duplicateCandidateOf: string | null;
}

/** REQ-LOAD-004: only a user-confirmed rest day counts toward observation_days. */
export interface RestDay {
  localDate: string;
  restConfirmedByUser: true;
  confirmedAtUtc: string;
}

export type SeverityBand = "NONE" | "MILD" | "MODERATE" | "SEVERE";

/** REQ-RLS-007: the summary row. `injury_reports` in the schema. */
export interface InjuryReport {
  id: string;
  localDate: string;
  hasIssue: boolean;
  severityBand: SeverityBand;
  bodyPart: string;
  createdAtUtc: string;
}

/** REQ-RLS-007: physically a separate table with its own RLS policy —
 *  free text is never a column on InjuryReport. */
export interface InjuryReportDetail {
  injuryReportId: string;
  freeText: string;
}

/** REQ-CONSENT-002: each scope is granted independently. */
export type ConsentScope =
  | "activity_summary"
  | "training_load"
  | "injury_status"
  | "injury_detail";

export interface ConsentGrant {
  scope: ConsentScope;
  teamId: string;
  granted: boolean;
  changedAtUtc: string;
}

export type MembershipStatus = "ACTIVE" | "INVITED" | "LEFT";

export interface TeamMembership {
  teamId: string;
  teamName: string;
  coachName: string;
  status: MembershipStatus;
  invitedAtUtc: string;
  joinedAtUtc: string | null;
  leftAtUtc: string | null;
}

/** REQ-AUTH-005: the user can list and revoke their own sessions. */
export interface AuthSession {
  id: string;
  device: string;
  ipMasked: string;
  location: string;
  lastActiveAtUtc: string;
  isCurrent: boolean;
}

/** REQ-AUDIT-001: the exact eight event types the SRS enumerates. */
export type AuditEvent =
  | "AUTH_LOGIN"
  | "AUTH_FAILURE"
  | "ROLE_CHANGE"
  | "CONSENT_GRANT"
  | "CONSENT_REVOKE"
  | "DATA_EXPORT"
  | "CROSS_TENANT_DENIED"
  | "BILLING_CHANGE";

export interface AuditEntry {
  id: string;
  event: AuditEvent;
  atUtc: string;
  /** REQ-AUDIT-002: never a password, token, injury free text, or raw payload. */
  summary: string;
}

/** REQ-WEATHER-001: four states, and the UI must say which one it is. */
export type WeatherState = "LIVE" | "CACHED" | "STALE" | "UNAVAILABLE";

export interface WeatherSnapshot {
  state: WeatherState;
  /** REQ-WEATHER-LOCATION-001: the city the user picked in settings. */
  city: string;
  temperatureC: number | null;
  humidityPct: number | null;
  observedAtUtc: string | null;
  /** Seconds of pace adjustment per km. null when the engine cannot run. */
  paceAdjustmentSecPerKm: number | null;
}

/** REQ-AI-004: every prescription number is server-rendered from this object.
 *  Nothing on it has passed through an LLM. */
export interface RecommendationObject {
  id: string;
  localDate: string;
  workoutType: string;
  durationMinutes: number;
  distanceKm: number | null;
  targetPaceSecPerKm: number | null;
  intensityLabel: string;
  adjustmentReasonCode: string;
  algorithmVersion: string;
}

/** REQ-AI-006: the LLM picks an id from this whitelist. Nothing more. */
export type ToneVariantId =
  | "SUPPORTIVE_A"
  | "SUPPORTIVE_B"
  | "STEADY_A"
  | "CAUTION_A"
  | "NEUTRAL_FALLBACK";

export interface ToneVariant {
  id: ToneVariantId;
  text: string;
  reviewedBy: string;
  reviewedAtUtc: string;
}

export interface Athlete {
  id: string;
  name: string;
  email: string;
  timezone: string;
  city: string;
  ageDeclaredOver18: boolean;
  ageDeclaredAtUtc: string;
}

export type TeamRole = "athlete" | "coach" | "head_coach" | "owner";

export interface Actor {
  userId: string;
  name: string;
  email: string;
  role: TeamRole;
  /** REQ-AUTH-007: owner / head_coach must have MFA satisfied. */
  mfaSatisfied: boolean;
}

/** Coach-side row. REQ-DATAOWN-001: a query-time projection, never a copy. */
export interface TeamAthleteProjection {
  athleteId: string;
  name: string;
  joinedAtUtc: string;
  status: MembershipStatus;
  /** Which scopes this athlete currently grants this team. */
  grantedScopes: ConsentScope[];
  acuteLoadAu: number | null;
  chronicLoadAu: number | null;
  loadRatio: number | null;
  dataQuality: DataQuality;
  lastActivityLocalDate: string | null;
  last14DaysLoad: number[];
  injuryHasIssue: boolean | null;
  injurySeverityBand: SeverityBand | null;
  injuryFreeText: string | null;
}

export interface AssignedWorkout {
  id: string;
  teamId: string;
  athleteId: string;
  localDate: string;
  title: string;
  durationMinutes: number;
  intensityLabel: string;
  status: "SCHEDULED" | "COMPLETED" | "MISSED";
}

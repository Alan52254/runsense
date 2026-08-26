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
  /** Optional block-by-block detail (warmup/interval/cooldown/recovery/jog),
   *  same shape AssignedWorkout.structure uses. Purely additive: durationMinutes/
   *  rpe still drive sessionLoad regardless of whether this is populated. */
  structure: WorkoutAssignmentSegment[];
  /** Device-reported training metrics (heart rate, cadence, elevation,
   *  calories, training effect) -- empty for every manual entry, since
   *  there's no live sensor path in this app today. Populated only via
   *  backend/scripts/backfill_garmin_metrics.py for imported history. */
  deviceMetrics: ActivityDeviceMetrics;
}

/** Mirrors apiClient.ts's ActivityDeviceMetricsWire -- see Activity.deviceMetrics. */
export interface ActivityDeviceMetrics {
  avgHeartRate?: number;
  maxHeartRate?: number;
  avgCadenceStepsPerMin?: number;
  maxCadenceStepsPerMin?: number;
  avgStrideLengthM?: number;
  elevationGainM?: number;
  elevationLossM?: number;
  calories?: number;
  aerobicTrainingEffect?: number;
  anaerobicTrainingEffect?: number;
  trainingEffectLabel?: string;
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

export type TimeOfDayLabel = "morning" | "midday" | "evening";

export interface TimeOfDayTemperatureEstimate {
  label: TimeOfDayLabel;
  hour: number;
  temperatureC: number;
  speedLossPct: number;
}

export interface WeatherSnapshot {
  state: WeatherState;
  /** REQ-WEATHER-LOCATION-001: the city the user picked in settings. */
  city: string;
  temperatureC: number | null;
  humidityPct: number | null;
  observedAtUtc: string | null;
  /** % of running speed lost right now vs. the athlete's sex-specific
   *  optimal-temperature curve (El Helou et al. 2012, PLOS ONE, Table S3),
   *  scaled by how typical today's temperature is for this month/city.
   *  null when the engine cannot run. */
  speedLossPct: number | null;
  /** The El Helou curve's own output, before the typical-for-this-month
   *  adjustment -- kept for transparency. */
  speedLossPctUnadjusted: number | null;
  /** Same curve, re-centered on climateNormalReferenceC (this city/month's
   *  typical temperature at the assumed reference run hour -- early
   *  evening) instead of the paper's absolute physiological optimum -- use
   *  this (not speedLossPct) for both a coach-assigned pace and the
   *  system's own recommended pace, since both are assumed calibrated for
   *  a typical evening run; applying speedLossPct on top would
   *  double-count that. null when the city has no climate-normal entry. */
  speedLossPctRelativeToNormal: number | null;
  /** This month's climate-normal MEAN temperature for `city`; null when the
   *  city has no climate-normal entry. Informational only -- not what
   *  speedLossPctRelativeToNormal is centered on; see climateNormalReferenceC. */
  climateNormalTemperatureC: number | null;
  /** What's climatologically typical for `city` at the assumed reference
   *  run hour (early evening -- a fixed hour, not whatever time it
   *  currently is) -- the actual reference speedLossPctRelativeToNormal
   *  and every timeOfDayEstimates slot are centered on, so they're
   *  directly comparable to each other. */
  climateNormalReferenceC: number | null;
  timeOfDayEstimates: TimeOfDayTemperatureEstimate[];
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
  segments?: WorkoutSegment[];
}

export type WorkoutSegmentKind = "warmup" | "work" | "recovery" | "set-rest" | "cooldown";

export interface WorkoutSegment {
  id: string;
  kind: WorkoutSegmentKind;
  label: string;
  distanceMeters?: number;
  durationSeconds?: number;
  repetitions?: number;
  targetPaceSecPerKm?: number | null;
  targetPaceRangeSecPerKm?: [number, number] | null;
  afterRepetition?: string;
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

/** Only two values because that's what the weather-pace research (see
 *  backend/app/weather_pace.py) reports separate curves for. null means
 *  "not set", not a third category -- the weather endpoint falls back to
 *  averaging both curves rather than guessing. */
export type AthleteSex = "male" | "female" | null;

export interface Athlete {
  id: string;
  name: string;
  email: string;
  timezone: string;
  city: string;
  sex: AthleteSex;
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
  structure?: WorkoutAssignmentSegment[];
}

export type WorkoutAssignmentSegment = {
  kind: "warmup" | "interval" | "recovery" | "rest" | "jog" | "cooldown";
  label: string;
  distanceMeters?: number;
  durationSeconds?: number;
  repetitions?: number;
  distancesMeters?: number[];
  pace?: string;
  /** interval only: rest between reps, e.g. 90 for a 90s recovery jog between reps. */
  restSeconds?: number;
  /** interval only, same length/order as distancesMeters: each rep's OWN
   *  pace, e.g. a negative-split or fading set. `pace` above stays the
   *  single averaged figure across the whole group; this is the granular
   *  version, populated only by backend/scripts/backfill_garmin_structure.py
   *  for imported history -- never set by the coach's workout builder,
   *  which prescribes one target pace per interval block, not per rep. */
  pacesPerRep?: string[];
};

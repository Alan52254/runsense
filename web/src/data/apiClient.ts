/* Thin client for the FastAPI backend's authenticated endpoints:
 *   POST /auth/demo-login   (only when COMPETITION_DEMO_ONLY=true)
 *   POST /activities, GET /activities
 *   GET /training-load/trend
 *
 * Weather, guidance, coach roster, membership/consent, and injury-report
 * endpoints are also available when the API base URL is configured.
 *
 * Point it at a running backend with VITE_API_BASE_URL, e.g.
 *   VITE_API_BASE_URL=http://localhost:8000 npm run dev
 * With no base URL configured the app stays in demo mode.
 */

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "";

export const apiConfigured = API_BASE_URL.length > 0;

export interface DemoLoginResult {
  accessToken: string;
  expiresAtUtc: string;
}

/** Opaque passthrough shape -- the backend stores/returns this array
 *  verbatim (see AssignedWorkoutWireResponse.structure), so it's typed the
 *  same camelCase way WorkoutAssignmentSegment is rather than snake_case. */
export interface ActivitySegmentWire {
  kind: "warmup" | "interval" | "recovery" | "rest" | "jog" | "cooldown";
  label: string;
  distanceMeters?: number;
  durationSeconds?: number;
  repetitions?: number;
  distancesMeters?: number[];
  pace?: string;
  restSeconds?: number;
}

/** Device-reported training metrics with no universal column of their own
 *  (heart rate, cadence, elevation, calories, training effect) -- empty
 *  for every manual entry. Read-only from this API today: nothing POSTs
 *  it, only backend/scripts/backfill_garmin_metrics.py writes it, directly
 *  via the database. Keys are typed here even though the backend stores
 *  it as an untyped passthrough dict, since that script is the sole
 *  producer and this is its exact output shape. */
export interface ActivityDeviceMetricsWire {
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

export interface CreateActivityWirePayload {
  client_mutation_id: string;
  duration_minutes: number;
  rpe: number;
  performed_at: string;
  distance_km?: number | null;
  structure?: ActivitySegmentWire[];
}

export interface CreateActivityWireResponse {
  id: string;
  athlete_id: string;
  client_mutation_id: string;
  provider: string;
  provider_activity_id: string | null;
  duration_minutes: number;
  rpe: number;
  performed_at: string;
  timezone_snapshot: string;
  local_training_date: string;
  session_load: number;
  unit: string;
  source_metric: string;
  server_version: number;
  created_at: string;
  structure: ActivitySegmentWire[];
  distance_km: number | null;
  device_metrics: ActivityDeviceMetricsWire;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** FastAPI always serves /openapi.json, so it doubles as a liveness probe.
 *  Backend down is a normal state here, not an error worth throwing over. */
export async function probeBackend(timeoutMs = 1500): Promise<boolean> {
  if (!apiConfigured) return false;
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}/openapi.json`, { signal: abort.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function demoLogin(
  email: string,
  password: string,
): Promise<DemoLoginResult> {
  const res = await fetch(`${API_BASE_URL}/auth/demo-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const body = await safeJson(res);
    throw new ApiError(
      res.status,
      String(body?.error ?? `HTTP_${res.status}`),
      res.status === 401 ? "帳號或密碼不正確" : "登入失敗，請稍後再試",
    );
  }

  const body = (await res.json()) as { access_token: string; expires_at: string };
  return { accessToken: body.access_token, expiresAtUtc: body.expires_at };
}

export async function createActivity(
  payload: CreateActivityWirePayload,
  accessToken: string,
): Promise<{ status: number; body: CreateActivityWireResponse }> {
  const res = await fetch(`${API_BASE_URL}/activities`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await safeJson(res);
    const code = String(body?.error ?? `HTTP_${res.status}`);
    throw new ApiError(res.status, code, describeCreateError(res.status, code));
  }

  // status is meaningful here (200 = idempotent replay vs 201 = created),
  // so this one keeps its own res.ok/status handling rather than going
  // through authenticatedRequest, which only ever returns the parsed body.
  return { status: res.status, body: (await res.json()) as CreateActivityWireResponse };
}

function describeCreateError(status: number, code: string): string {
  if (code === "PROFILE_TIMEZONE_NOT_SET") return "個人設定尚未指定時區，請先到設定完成";
  if (code === "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")
    return "這筆紀錄的識別碼已被用於不同內容，請重新建立";
  if (code === "NOT_AUTHORIZED") return "沒有權限，請重新登入";
  if (status === 422) return "輸入內容不符合格式";
  if (status >= 500) return "伺服器暫時無法回應，稍後會自動重試";
  return "建立失敗";
}

async function safeJson(res: Response): Promise<Record<string, unknown> | null> {
  try {
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** FastAPI's own 422 response shape (`{"detail": [{"loc": [...], "msg": ...}]}`)
 *  never carries the `{"error": "SOME_CODE"}` shape every handled error in
 *  this app uses -- so a schema-validation failure (an empty required field,
 *  an out-of-range number) always fell through every endpoint's
 *  describeError callback as an opaque "request failed", with no hint which
 *  field or why. This surfaces the actual field + reason instead. */
function describeValidationError(body: Record<string, unknown> | null): string | null {
  const detail = body?.detail;
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const first = detail[0] as { loc?: unknown; msg?: unknown };
  const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
  const msg = typeof first.msg === "string" ? first.msg : "格式不正確";
  return field ? `${field}：${msg}` : msg;
}

/* ---------------- shared authenticated-request seam ----------------
 * Every authenticated call (create/history/trend) shares the same
 * fetch/parse/error-code shape. One helper here means a new endpoint is a
 * few lines, not a fourth copy of try/parse/throw. */

async function authenticatedRequest<T>(
  path: string,
  accessToken: string,
  init?: RequestInit,
  describeError?: (status: number, code: string) => string,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${accessToken}`,
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await safeJson(res);
    const code = String(body?.error ?? `HTTP_${res.status}`);
    const validationDetail = code === "HTTP_422" ? describeValidationError(body) : null;
    throw new ApiError(
      res.status,
      code,
      validationDetail ?? (describeError ? describeError(res.status, code) : `請求失敗（${res.status}）`),
    );
  }

  return (await res.json()) as T;
}

export interface ActivityHistoryResponse {
  items: CreateActivityWireResponse[];
  next_cursor: string | null;
}

export async function getActivityHistory(
  accessToken: string,
  options: { cursor?: string | null; limit?: number } = {},
): Promise<ActivityHistoryResponse> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  const query = params.toString();
  return authenticatedRequest<ActivityHistoryResponse>(
    `/activities${query ? `?${query}` : ""}`,
    accessToken,
  );
}

/** DELETE /activities/{id} returns 204 with no body -- authenticatedRequest
 *  always parses a JSON body, so this uses the same hand-rolled fetch as
 *  revokeMySession above. */
export async function deleteActivity(accessToken: string, activityId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/activities/${activityId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new ApiError(res.status, String(body?.error ?? `HTTP_${res.status}`), "刪除訓練紀錄失敗");
  }
}

export interface TrainingLoadPointWire {
  date: string;
  session_load: number;
  acute_load: number;
  chronic_load: number;
  load_ratio: number | null;
  data_quality: "SUFFICIENT" | "LOW" | "INSUFFICIENT";
  observation_days: number;
  algorithm_version: string;
  schema_version: number;
  computed_at: string;
  input_snapshot_hash: string;
}

export interface TrainingLoadSeriesWire {
  unit: string;
  source_metric: string;
  points: TrainingLoadPointWire[];
}

export interface TrainingLoadTrendWireResponse {
  start_date: string;
  end_date: string;
  series: TrainingLoadSeriesWire[];
}

export async function getTrainingLoadTrend(
  accessToken: string,
  endDate?: string,
): Promise<TrainingLoadTrendWireResponse> {
  const query = endDate ? `?end_date=${endDate}` : "";
  return authenticatedRequest<TrainingLoadTrendWireResponse>(
    `/training-load/trend${query}`,
    accessToken,
  );
}

export interface ProfileWireResponse {
  city: string | null;
  timezone: string;
  sex: "male" | "female" | null;
}

export async function updateProfile(
  accessToken: string,
  patch: { city?: string; timezone?: string; sex?: "male" | "female" },
): Promise<ProfileWireResponse> {
  return authenticatedRequest<ProfileWireResponse>("/profile", accessToken, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export interface TimeOfDayTemperatureEstimateWireResponse {
  label: "morning" | "midday" | "evening";
  hour: number;
  temperature_c: number;
  speed_loss_pct: number;
}

export interface WeatherWireResponse {
  state: "LIVE" | "CACHED" | "STALE" | "UNAVAILABLE";
  city: string | null;
  temperature_c: number | null;
  humidity_pct: number | null;
  observed_at: string | null;
  /** % of running speed lost right now -- the El Helou et al. (2012, Table
   *  S3) sex-specific curve, scaled by how today's temperature compares to
   *  what's typical this month/city (see climate_normal_temperature_c).
   *  Converting to a pace needs a baseline pace this doesn't carry -- see
   *  DashboardScreen.tsx's adjustedTargetPace. */
  speed_loss_pct: number | null;
  /** The El Helou curve's own output, before the typical-for-this-month
   *  adjustment -- kept for transparency. */
  speed_loss_pct_unadjusted: number | null;
  /** Same curve re-centered on climate_normal_reference_c (this city/
   *  month's typical temperature at the assumed reference run hour --
   *  early evening) instead of the paper's absolute optimum -- use this
   *  for both a coach-assigned pace and the system's own recommended
   *  pace, both assumed calibrated for a typical evening run (see
   *  weather_pace.py's speed_loss_pct_relative_to_normal docstring). null
   *  when the city isn't in the climate-normal table. */
  speed_loss_pct_relative_to_normal: number | null;
  /** This month's climate-normal MEAN temperature for `city`. null when the
   *  city isn't in that table -- speed_loss_pct then equals
   *  speed_loss_pct_unadjusted and time_of_day_estimates is empty.
   *  Informational only -- not what speed_loss_pct_relative_to_normal is
   *  centered on; see climate_normal_reference_c for that. */
  climate_normal_temperature_c: number | null;
  /** What's climatologically typical for `city` at the assumed reference
   *  run hour (early evening -- a fixed hour, not whatever time it
   *  currently is; the diurnal model applied to this month's normal
   *  low/high) -- the actual reference speed_loss_pct_relative_to_normal
   *  and every time_of_day_estimates slot are centered on, so they're
   *  directly comparable to each other. Falls back to
   *  climate_normal_temperature_c when sunrise/sunset data isn't
   *  available. */
  climate_normal_reference_c: number | null;
  time_of_day_estimates: TimeOfDayTemperatureEstimateWireResponse[];
  /** One entry per value passed in `segmentOffsetsMin`, same order --
   *  see SegmentTemperatureEstimateWireResponse. Empty when no offsets
   *  were requested, or under the same no-climate-normal/no-sun-time
   *  conditions that empty time_of_day_estimates. */
  segment_estimates: SegmentTemperatureEstimateWireResponse[];
}

export interface SegmentTemperatureEstimateWireResponse {
  /** Echoed back from the request -- matches an entry in the
   *  `segmentOffsetsMin` array passed to getWeather, in the same order. */
  offset_min: number;
  temperature_c: number;
  /** Same meaning as TimeOfDayTemperatureEstimateWireResponse.speed_loss_pct
   *  (compared against the shared early-evening reference), just at this
   *  caller-supplied offset instead of a fixed slot. */
  speed_loss_pct: number;
}

/** `segmentOffsetsMin`: minutes from now each requested estimate should be
 *  computed at -- e.g. the estimated start time of each block in a
 *  multi-segment workout (see paceCalc.ts's computeSegmentStartOffsetsMinutes).
 *  Omit for the plain "now" weather snapshot; segment_estimates comes back
 *  empty either way if omitted. */
export async function getWeather(
  accessToken: string,
  segmentOffsetsMin?: number[],
): Promise<WeatherWireResponse> {
  const query = segmentOffsetsMin?.length
    ? `?${segmentOffsetsMin.map((offset) => `segment_offsets_min=${encodeURIComponent(offset)}`).join("&")}`
    : "";
  return authenticatedRequest<WeatherWireResponse>(`/weather${query}`, accessToken);
}

export interface RecommendationWireResponse {
  workout_type: string;
  duration_minutes: number;
  distance_km: number | null;
  target_pace_sec_per_km: number | null;
  intensity_label: string;
  adjustment_reason_code: string;
  algorithm_version: string;
  segments: Array<{
    id: string;
    kind: string;
    label: string;
    distance_meters: number | null;
    duration_seconds: number | null;
    repetitions: number | null;
    target_pace_sec_per_km: number | null;
    target_pace_range_sec_per_km: number[] | null;
    after_repetition: string | null;
  }>;
}

export interface GuidanceWireResponse {
  local_date: string;
  recommendation: RecommendationWireResponse;
  tone_variant_id: string;
  tone_text: string;
  tone_reviewed_by: string;
  computed_at: string;
}

export async function getTodaysGuidance(
  accessToken: string,
  llmToneEnabled: boolean,
): Promise<GuidanceWireResponse> {
  return authenticatedRequest<GuidanceWireResponse>(
    `/guidance/today?llm_tone_enabled=${llmToneEnabled}`,
    accessToken,
  );
}

/* ---------------- coach team overview / athlete detail ----------------
 * GET /teams/mine, GET /teams/{team_id}/roster, GET /teams/{team_id}/athletes/{athlete_id}
 * See backend/app/routes/teams.py. A Coach Roster Row is a query-time
 * projection: every gated field below is null unless the athlete's currently
 * granted Consent Scopes cover it -- never a masked-but-present value. */

export interface TeamSummaryWireResponse {
  team_id: string;
  name: string;
  role: string;
}

export interface MyTeamsWireResponse {
  items: TeamSummaryWireResponse[];
}

export async function getMyTeams(accessToken: string): Promise<MyTeamsWireResponse> {
  return authenticatedRequest<MyTeamsWireResponse>("/teams/mine", accessToken);
}

export interface CoachRosterRowWireResponse {
  team_id: string;
  athlete_id: string;
  name: string;
  status: "ACTIVE" | "INVITED" | "LEFT";
  joined_at: string | null;
  granted_scopes: string[];
  last_activity_local_date: string | null;
  acute_load_au: number | null;
  chronic_load_au: number | null;
  load_ratio: number | null;
  data_quality: "SUFFICIENT" | "LOW" | "INSUFFICIENT" | null;
  last_14_days_load: number[];
  injury_has_issue: boolean | null;
  injury_severity_band: string | null;
  injury_free_text: string | null;
}

export interface TeamRosterWireResponse {
  team_id: string;
  items: CoachRosterRowWireResponse[];
}

export async function getTeamRoster(
  accessToken: string,
  teamId: string,
): Promise<TeamRosterWireResponse> {
  return authenticatedRequest<TeamRosterWireResponse>(`/teams/${teamId}/roster`, accessToken);
}

export async function getTeamAthlete(
  accessToken: string,
  teamId: string,
  athleteId: string,
): Promise<CoachRosterRowWireResponse> {
  return authenticatedRequest<CoachRosterRowWireResponse>(
    `/teams/${teamId}/athletes/${athleteId}`,
    accessToken,
  );
}

/** The Completed Activity (if any) that actually happened on one Local
 *  Training Date, from a coach's point of view -- reuses the exact same
 *  wire shape as the athlete's own GET /activities. Empty `items` covers
 *  both "no run that day" and "activity_summary not granted" alike; the
 *  server never distinguishes them (see teams.py's route docstring). */
export async function getTeamAthleteActivities(
  accessToken: string,
  teamId: string,
  athleteId: string,
  localDate: string,
): Promise<ActivityHistoryResponse> {
  return authenticatedRequest<ActivityHistoryResponse>(
    `/teams/${teamId}/athletes/${athleteId}/activities?local_date=${localDate}`,
    accessToken,
  );
}

export type ConsentScopeWire =
  | "activity_summary"
  | "training_load"
  | "injury_status"
  | "injury_detail";

export interface TeamMembershipWireResponse {
  team_id: string;
  team_name: string;
  coach_name: string;
  role: string;
  status: "ACTIVE" | "INVITED" | "LEFT";
  invited_at: string;
  joined_at: string | null;
  left_at: string | null;
}

export async function getMyTeamMemberships(accessToken: string) {
  return authenticatedRequest<{ items: TeamMembershipWireResponse[] }>(
    "/me/team-memberships",
    accessToken,
  );
}

export async function updateMyTeamMembership(
  accessToken: string,
  teamId: string,
  action: "accept" | "decline" | "leave",
) {
  return authenticatedRequest<TeamMembershipWireResponse>(
    `/me/team-memberships/${teamId}`,
    accessToken,
    { method: "PATCH", body: JSON.stringify({ action }) },
  );
}

export interface ConsentGrantWireResponse {
  team_id: string;
  scope: ConsentScopeWire;
  granted: boolean;
  changed_at: string;
}

export async function getMyConsentGrants(accessToken: string) {
  return authenticatedRequest<{ items: ConsentGrantWireResponse[] }>(
    "/me/consent-grants",
    accessToken,
  );
}

export async function updateMyConsentGrant(
  accessToken: string,
  teamId: string,
  scope: ConsentScopeWire,
  granted: boolean,
) {
  return authenticatedRequest<ConsentGrantWireResponse>(
    `/me/consent-grants/${scope}`,
    accessToken,
    { method: "PATCH", body: JSON.stringify({ team_id: teamId, granted }) },
  );
}

export interface InjuryReportWireResponse {
  id: string;
  athlete_id: string;
  client_mutation_id: string;
  has_issue: boolean;
  severity_band: "NONE" | "MILD" | "MODERATE" | "SEVERE";
  body_part: string | null;
  reported_at: string;
  timezone_snapshot: string;
  local_training_date: string;
  free_text: string | null;
  created_at: string;
}

export async function getInjuryReports(accessToken: string) {
  return authenticatedRequest<{ items: InjuryReportWireResponse[] }>(
    "/injury-reports",
    accessToken,
  );
}

export async function createInjuryReport(
  accessToken: string,
  payload: {
    client_mutation_id: string;
    has_issue: boolean;
    severity_band: "NONE" | "MILD" | "MODERATE" | "SEVERE";
    body_part: string | null;
    free_text: string | null;
    reported_at: string;
  },
) {
  return authenticatedRequest<InjuryReportWireResponse>(
    "/injury-reports",
    accessToken,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

/* ---------------- Settings: Security/Privacy/Integration ----------------
 * GET/DELETE /me/settings/sessions, POST /me/settings/mfa/verify,
 * GET /me/settings/privacy/export, POST /me/settings/privacy/deletion-request,
 * GET /me/settings/integrations/garmin, GET /me/settings/audit-log.
 * See backend/app/routes/settings.py. Demo-appropriate scope, not full
 * compliance infrastructure -- see backend/README.md. */

export interface AuthSessionWireResponse {
  id: string;
  device: string;
  ip_masked: string;
  location: string;
  last_active_at: string;
  is_current: boolean;
}

export async function getMySessions(accessToken: string) {
  return authenticatedRequest<{ items: AuthSessionWireResponse[] }>(
    "/me/settings/sessions",
    accessToken,
  );
}

export async function revokeMySession(accessToken: string, sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/me/settings/sessions/${sessionId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new ApiError(res.status, String(body?.error ?? `HTTP_${res.status}`), "撤銷 session 失敗");
  }
}

export async function verifyMyMfa(accessToken: string, code: string) {
  return authenticatedRequest<{ mfa_satisfied: boolean }>(
    "/me/settings/mfa/verify",
    accessToken,
    { method: "POST", body: JSON.stringify({ code }) },
    (_status, apiCode) => (apiCode === "INVALID_MFA_CODE" ? "驗證碼不正確" : "驗證失敗"),
  );
}

export async function exportMyPrivacyData(accessToken: string) {
  return authenticatedRequest<Record<string, unknown>>(
    "/me/settings/privacy/export",
    accessToken,
  );
}

export async function requestMyAccountDeletion(accessToken: string) {
  return authenticatedRequest<{ deletion_requested_at: string }>(
    "/me/settings/privacy/deletion-request",
    accessToken,
    { method: "POST" },
  );
}

export async function getGarminIntegrationStatus(accessToken: string) {
  return authenticatedRequest<{ enabled: boolean; reason: string }>(
    "/me/settings/integrations/garmin",
    accessToken,
  );
}

export interface AuditLogEntryWireResponse {
  id: string;
  event: string;
  created_at: string;
  summary: string;
}

export async function getMyAuditLog(accessToken: string) {
  return authenticatedRequest<{ items: AuditLogEntryWireResponse[] }>(
    "/me/settings/audit-log",
    accessToken,
  );
}

/* ---------------- Coach Assignments (AssignedWorkout) ----------------
 * POST/GET /teams/{team_id}/assignments (coach), GET /me/assigned-workouts
 * (athlete). See backend/app/routes/assignments.py. */

export interface AssignedWorkoutWireResponse {
  id: string;
  team_id: string;
  athlete_id: string;
  local_date: string;
  title: string;
  duration_minutes: number;
  intensity_label: string;
  status: "SCHEDULED" | "COMPLETED" | "MISSED";
  created_at: string;
  structure: ActivitySegmentWire[];
  /** false for strength / core: scheduled to be seen, never tracked as done */
  tracked?: boolean;
  notes?: string | null;
}

export async function getTeamAssignments(accessToken: string, teamId: string) {
  return authenticatedRequest<{ items: AssignedWorkoutWireResponse[] }>(
    `/teams/${teamId}/assignments`,
    accessToken,
  );
}

export async function createTeamAssignment(
  accessToken: string,
  teamId: string,
  payload: {
    athlete_id: string;
    local_date: string;
    title: string;
    duration_minutes: number;
    intensity_label: string;
    structure: Array<Record<string, unknown>>;
  },
) {
  return authenticatedRequest<AssignedWorkoutWireResponse>(
    `/teams/${teamId}/assignments`,
    accessToken,
    { method: "POST", body: JSON.stringify(payload) },
    (_status, code) =>
      code === "ASSIGNMENT_ATHLETE_NOT_ELIGIBLE"
        ? "這名選手目前不是有效隊員，無法指派"
        : "新增指派失敗",
  );
}

export async function deleteTeamAssignment(
  accessToken: string,
  teamId: string,
  assignmentId: string,
): Promise<void> {
  // A 204 No Content response has no body -- authenticatedRequest always
  // calls res.json() on success, so this follows revokeMySession's
  // hand-rolled fetch instead, same as that other DELETE endpoint.
  const res = await fetch(`${API_BASE_URL}/teams/${teamId}/assignments/${assignmentId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    const body = await safeJson(res);
    const code = String(body?.error ?? `HTTP_${res.status}`);
    throw new ApiError(
      res.status,
      code,
      code === "ASSIGNMENT_NOT_FOUND" ? "找不到這筆指派，可能已被刪除" : "刪除指派失敗",
    );
  }
}

export async function getMyAssignedWorkouts(accessToken: string) {
  return authenticatedRequest<{ items: AssignedWorkoutWireResponse[] }>(
    "/me/assigned-workouts",
    accessToken,
  );
}

/* ---------------- Training-plan ranker (health-training-intelligence) ----------------
 * GET /training-plan/today. See backend/app/routes/training_plan.py. Returns
 * auditable candidate workouts with a deterministic ranker's abstain decision
 * and which input features it actually had -- not an opaque score. */

export type PlanWorkoutType = "REST_DAY" | "REST_AND_SEEK_CARE" | "RECOVERY_RUN" | "EASY_RUN" | "STEADY_RUN";

export interface TrainingPlanCandidateWire {
  candidate_id: string;
  workout_type: PlanWorkoutType;
  duration_minutes: number;
  distance_km: number;
  running_allowed: boolean;
  provenance_rule_ids: string[];
  /** Deterministic ranker's score for this candidate (higher = preferred),
   *  and the plain-language reasons behind it. Null score in the cold-start
   *  fallback, where candidates are ordered gentlest-first without scoring. */
  score: number | null;
  rationale: string[];
}

export interface TrainingPlanInputsWire {
  acute_load: number | null;
  chronic_load: number | null;
  acute_chronic_ratio: number | null;
  observation_days: number;
  temperature_c: number | null;
  weather_state: "LIVE" | "CACHED" | "STALE" | "UNAVAILABLE";
  triage_urgency: "EMERGENCY" | "PROMPT_CLINICIAN" | "SELF_CARE_NEXT_STEP" | null;
}

export interface TrainingPlanWireResponse {
  local_date: string;
  ranker_version: string;
  abstained: boolean;
  abstention_reason: string | null;
  confidence: number | null;
  /** Machine code for why the ranking came out this way -- the UI maps it to
   *  a sentence. e.g. LOAD_ELEVATED_FAVOR_RECOVERY, COLD_START_ABSTAIN. */
  reason_code: string;
  inputs: TrainingPlanInputsWire;
  feature_coverage: Record<"training_load" | "weather" | "injury_triage", boolean>;
  candidates: TrainingPlanCandidateWire[];
  scenario?: {
    label: string;
    /** False when the Athlete is looking at stated conditions rather than
     *  their actual ones -- the UI must never present those as instructions. */
    is_today: boolean;
    overridden_fields: string[];
    available_minutes: number | null;
    humidity_pct: number | null;
    excluded_by_time_budget: string[];
    /** % of running speed these conditions cost relative to a typical
     *  evening for this city and month. Null when unknown. */
    speed_loss_pct: number | null;
    /** True when the conditions sit outside the published curve's measured
     *  band, so the figure must be shown as an estimate beyond measurement. */
    pacing_is_extrapolated: boolean;
  };
}

export async function getTrainingPlanToday(
  accessToken: string,
): Promise<TrainingPlanWireResponse> {
  return authenticatedRequest<TrainingPlanWireResponse>("/training-plan/today", accessToken);
}

/** The conditions a plan is worked out against. Facts only -- there is
 *  deliberately no way to state a distance, duration, pace or intensity
 *  here, so exploring conditions can never become prescribing a workout. */
export interface ScenarioOverrideWire {
  local_date?: string;
  temperature_c?: number;
  humidity_pct?: number;
  available_minutes?: number;
  reported_body_part?: string;
  reported_severity_band?: "MILD" | "MODERATE" | "SEVERE";
  label?: string;
}

/** POST /training-plan/evaluate -- the same evaluation `today` runs, against
 *  stated conditions instead of the current ones. An empty override is today. */
export async function evaluateTrainingPlan(
  accessToken: string,
  override: ScenarioOverrideWire,
): Promise<TrainingPlanWireResponse> {
  return authenticatedRequest<TrainingPlanWireResponse>("/training-plan/evaluate", accessToken, {
    method: "POST",
    body: JSON.stringify(override),
  });
}

/* GET /training-plan/model-report -- the offline, leakage-safe benchmark for
 * the plan ranker (backend/ml), scoped to this athlete's history summary.
 * The evaluation set is deterministic synthetic data; production ranking
 * stays deterministic (ADR 0002). */

export interface PlanModelReportWire {
  athlete_history: {
    completed_activities: number;
    history_span_days: number | null;
    days_since_last_activity: number | null;
    observation_days: number;
    acute_load: number | null;
    chronic_load: number | null;
    acute_chronic_ratio: number | null;
  };
  athlete_features: {
    available: boolean;
    reason?: string;
    n_days?: number;
    top_choice_match_rate?: number;
    feature_contract?: string[];
    days?: Array<{
      day_index: number;
      predicted: PlanWorkoutType;
      actual: PlanWorkoutType;
      matched: boolean;
      acute_chronic_ratio: number;
      soreness_ord: number;
      weather_backed: boolean;
    }>;
    note?: string;
  };
  evaluation: {
    feature_names: string[];
    n_rows: number;
    n_groups: number;
    n_queries: number;
    baseline_aggregate: Record<string, number>;
    tree_aggregate: Record<string, unknown>;
    per_fold: Array<Record<string, unknown>>;
    winner_declared: boolean;
    production_ranker: string;
    note: string;
  };
  production_ranker: string;
  winner_declared: boolean;
  note: string;
}

export async function getPlanModelReport(
  accessToken: string,
): Promise<PlanModelReportWire> {
  return authenticatedRequest<PlanModelReportWire>("/training-plan/model-report", accessToken);
}

/* ---------------- Injury guidance / health coach (health-guidance) ----------------
 * POST /injury-guidance. See backend/app/routes/injury_guidance.py. A fixed
 * safety-triage decides urgency and whether running is allowed; only then is
 * cited educational copy attached. The three flags below are the demo subset
 * the mobile client also sends. */

export interface InjuryGuidanceCitationWire {
  evidence_id: string;
  title: string;
  publisher: string;
  source_url: string;
}

export type InjuryGuidanceUrgency =
  | "EMERGENCY"
  | "PROMPT_CLINICIAN"
  | "SELF_CARE_NEXT_STEP";

export interface InjuryGuidanceWireResponse {
  injury_report_id: string;
  urgency: InjuryGuidanceUrgency;
  running_allowed: boolean;
  summary: string;
  next_steps: string[];
  citations: InjuryGuidanceCitationWire[];
  disclaimer: string;
  rule_version: string;
  matched_rule_ids: string[];
  provider_name: string;
  used_fallback: boolean;
  fallback_reason: string | null;
}

export interface InjuryGuidanceFlags {
  chestPainOrBreathingDifficulty: boolean;
  collapseConfusionOrExtremeHeatIllness: boolean;
  localizedBonePainWorseWithWeightBearing: boolean;
}

export async function createInjuryGuidance(
  accessToken: string,
  injuryReportId: string,
  flags: InjuryGuidanceFlags,
): Promise<InjuryGuidanceWireResponse> {
  return authenticatedRequest<InjuryGuidanceWireResponse>(
    "/injury-guidance",
    accessToken,
    {
      method: "POST",
      body: JSON.stringify({
        injury_report_id: injuryReportId,
        chest_pain_or_breathing_difficulty: flags.chestPainOrBreathingDifficulty,
        collapse_confusion_or_extreme_heat_illness: flags.collapseConfusionOrExtremeHeatIllness,
        localized_bone_pain_worse_with_weight_bearing:
          flags.localizedBonePainWorseWithWeightBearing,
      }),
    },
  );
}

export interface CoachChatMessage {
  role: "user" | "assistant";
  content: string;
}

export async function chatWithCoach(
  accessToken: string,
  messages: CoachChatMessage[],
  bodyPart?: string,
  severityBand?: string,
): Promise<{ response: string }> {
  return authenticatedRequest<{ response: string }>(
    "/guidance/chat",
    accessToken,
    {
      method: "POST",
      body: JSON.stringify({
        messages,
        body_part: bodyPart,
        severity_band: severityBand,
      }),
    },
  );
}

/** One thing the server reported while working on an answer. */
export type CoachStreamEvent =
  | { kind: "step"; step: Record<string, unknown> }
  | { kind: "delta"; delta: string }
  | { kind: "proposal"; proposal: Record<string, unknown> };

/** POST /guidance/chat/stream -- the answer as it is produced, together with
 *  what the coach did to produce it and any plan it worked out from facts the
 *  Athlete stated. */
export async function streamChatWithCoach(
  accessToken: string,
  messages: CoachChatMessage[],
  onEvent: (event: CoachStreamEvent) => void,
  onComplete: () => void,
  bodyPart?: string,
  severityBand?: string,
): Promise<void> {
  const base = API_BASE_URL || "http://localhost:8000"; // "/api" (same origin) in the phone setup
  const url = `${base}/guidance/chat/stream`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messages,
      body_part: bodyPart,
      severity_band: severityBand,
    }),
  });

  if (!res.ok || !res.body) {
    throw new Error(`Stream request failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      if (!chunk.startsWith("data: ")) continue;
      const payload = chunk.slice("data: ".length).trim();
      if (payload === "[DONE]") {
        onComplete();
        return;
      }
      try {
        const parsed = JSON.parse(payload) as Record<string, unknown>;
        if (typeof parsed.delta === "string") {
          onEvent({ kind: "delta", delta: parsed.delta });
        } else if (typeof parsed.step === "string") {
          onEvent({ kind: "step", step: parsed });
        } else if (parsed.proposal && typeof parsed.proposal === "object") {
          onEvent({ kind: "proposal", proposal: parsed.proposal as Record<string, unknown> });
        }
      } catch {
        // A chunk split mid-JSON: the next read completes it.
      }
    }
  }
  onComplete();
}

/** POST /guidance/proposals/{id}/accept -- apply a Coach Proposal to the day.
 *  reason COACH_SCHEDULED: the coach has scheduled that day, so nothing was
 *  applied -- the Athlete can send the suggestion to the coach instead. */
export async function acceptCoachProposal(
  accessToken: string,
  proposalId: string,
): Promise<{ applied: boolean; reason?: string | null }> {
  return authenticatedRequest<{ applied: boolean; reason?: string | null }>(
    `/guidance/proposals/${proposalId}/accept`,
    accessToken,
    { method: "POST" },
  );
}

/** POST /guidance/proposals/{id}/share -- send it to the coach as a Coach
 *  Suggestion in the athlete's one-to-one chat room. Nothing is scheduled. */
export async function shareCoachProposal(
  accessToken: string,
  proposalId: string,
): Promise<{ room_ids: string[] }> {
  return authenticatedRequest<{ room_ids: string[] }>(
    `/guidance/proposals/${proposalId}/share`,
    accessToken,
    { method: "POST" },
    () => "傳送給教練失敗",
  );
}

/** POST /guidance/proposals/{id}/dismiss -- decline it; nothing changes. */
export async function dismissCoachProposal(
  accessToken: string,
  proposalId: string,
): Promise<{ applied: boolean }> {
  return authenticatedRequest<{ applied: boolean }>(
    `/guidance/proposals/${proposalId}/dismiss`,
    accessToken,
    { method: "POST" },
  );
}

/** One piece of reviewed guidance the coach can lean on. */
export interface GuidancePassageWire {
  evidence_id: string;
  title: string;
  publisher: string;
  source_url: string;
  text: string;
  /** PROTECTION / LOADING / RETURN_TO_RUN, or null when stage-independent. */
  phase: string | null;
  phase_purpose: string | null;
  progression_criterion: string | null;
  body_parts: string[];
}

/** GET /guidance/library -- browse the reviewed guidance, filtered by what
 *  the Athlete is actually asking about. */
export async function browseGuidanceLibrary(
  accessToken: string,
  filters: { bodyPart?: string; phase?: string; topic?: string } = {},
): Promise<{ passages: GuidancePassageWire[] }> {
  const params = new URLSearchParams();
  if (filters.bodyPart) params.set("body_part", filters.bodyPart);
  if (filters.phase) params.set("phase", filters.phase);
  if (filters.topic) params.set("topic", filters.topic);
  const query = params.toString();
  return authenticatedRequest<{ passages: GuidancePassageWire[] }>(
    query ? `/guidance/library?${query}` : "/guidance/library",
    accessToken,
  );
}
/* ---------------- Real lap data + AI workout analysis ----------------
 * backend/app/routes/workout_analysis.py. Only activities imported with
 * their Garmin .fit file have telemetry; every other activity 404s with
 * TELEMETRY_NOT_FOUND and keeps the History screen's estimated laps. */

export type SegmentRole = "warmup" | "work" | "rest" | "set_rest" | "strides" | "cooldown" | "steady";
export type WorkoutSessionType = "intervals" | "tempo" | "easy" | "long" | "race" | "other";

export interface TelemetryLapWire {
  lap_number: number;
  start_s: number;
  end_s: number;
  distance_m: number | null;
  timer_s: number | null;
  pace_s_per_km: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_cadence: number | null;
  trigger: string | null;
  role: SegmentRole | null;
}

export interface PrescriptionBlockWire {
  reps: number;
  distance_m: number | null;
  duration_s: number | null;
  targets_s_per_km: number[];
  rest_s: number | null;
  rest_after_s?: number | null;
  targets_inferred?: boolean;
}

export type PrescriptionSource = "coach_assignment" | "athlete_text" | "activity_name" | "inferred";

export interface PrescriptionWire {
  source: PrescriptionSource;
  source_label?: string;
  title: string;
  raw_text: string | null;
  blocks: PrescriptionBlockWire[];
  gradable?: boolean;
  issues?: string[];
}

export interface LinkedRecordWire {
  activity_id: string;
  start_local: string;
  duration_s: number;
  distance_km: number;
  avg_hr: number | null;
}

export interface LinkedRecordsWire {
  warmup?: LinkedRecordWire;
  cooldown?: LinkedRecordWire;
}

export interface ActivityTelemetryWire {
  activity_id: string;
  /** "garmin_fit" for a recording, "simulated" for the demo's simulated athlete */
  source: string;
  activity_name: string | null;
  prescription: PrescriptionWire | null;
  /** the coach's title when the coach prescribed an easy day */
  coach_easy_day: string | null;
  linked: LinkedRecordsWire;
  sport: string | null;
  sub_sport: string | null;
  device: string | null;
  laps: TelemetryLapWire[];
  detection: { kind: string; signature: string | null; confidence: number };
  has_analysis: boolean;
  roles_from: "analysis" | "detection";
}

export interface WorkoutSegmentWire {
  role: SegmentRole;
  start_s: number;
  end_s: number;
  nominal_m?: number | null;
  nominal_s?: number | null;
  interruptions?: number[][];
}

export interface SegmentStatsWire {
  index: number;
  role: SegmentRole;
  start_s: number;
  end_s: number;
  elapsed_s: number;
  moving_s: number;
  gps_distance_m: number;
  distance_m: number;
  nominal_m: number | null;
  nominal_s: number | null;
  pace_s_per_km: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  hr_coverage: number;
  avg_cadence: number | null;
  interruptions_s: number;
  hr_end?: number | null;
  hr_start?: number | null;
  first_half_pace?: number;
  second_half_pace?: number;
  rest_type?: "standing" | "walking" | "jogging";
  hr_drop?: number;
  hr_peak_into_rest?: number;
  rep_number?: number;
  target_pace_s_per_km?: number;
  target_label?: string;
  target_dev_pct?: number;
  target_dev_s?: number;
}

export interface HrProfileWire {
  max_hr: number | null;
  max_hr_source: "manual" | "device" | "history" | "age_formula" | null;
  resting_hr: number | null;
  resting_hr_source: "manual" | "device" | null;
  zone_method: string;
  zone_tops: number[];
  history_peak_30s: number | null;
  notes: string[];
}

export interface WorkoutFindingWire {
  code: string;
  severity: "critical" | "warning" | "positive" | "info";
  title: string;
  detail: string;
  advice: string | null;
  evidence: Record<string, unknown>;
}

export interface WorkoutAnalysisWire {
  activity_id: string;
  session_type: WorkoutSessionType;
  segments: WorkoutSegmentWire[];
  signature: string | null;
  signature_label: string;
  target_pace_s_per_km: number | null;
  segment_stats: SegmentStatsWire[];
  summary: Record<string, unknown> & {
    hr_profile: HrProfileWire;
    zone_seconds: number[];
    total_distance_m: number;
    total_elapsed_s: number;
  };
  findings: WorkoutFindingWire[];
  data_notes: string[];
  narrative: string;
  narrative_source: "llm" | "offline";
  narrative_model: string | null;
  fallback_reason: string | null;
  updated_at: string;
}

export interface WorkoutDetectionWire {
  activity_id: string;
  detection: {
    kind: "intervals" | "tempo" | "continuous" | "insufficient";
    method: string | null;
    segments: WorkoutSegmentWire[];
    confidence: number;
    reasons: string[];
    hints: { type: "merge"; work_index: number; total_m: number }[];
    signature: string | null;
    time_based?: boolean;
  };
  suggested_session_type: WorkoutSessionType;
  segments_preview: SegmentStatsWire[];
  duration_s: number;
  sub_sport: string | null;
  laps: TelemetryLapWire[];
  hr_profile: HrProfileWire;
  hr_manual: { max_hr_bpm: number | null; resting_hr_bpm: number | null; birth_year: number | null };
  easy_pace_s_per_km: number | null;
  saved_analysis: WorkoutAnalysisWire | null;
  activity_name: string | null;
  prescription: PrescriptionWire | null;
  has_real_prescription: boolean;
  linked: LinkedRecordsWire;
}

export async function getActivityTelemetry(accessToken: string, activityId: string) {
  return authenticatedRequest<ActivityTelemetryWire>(`/activities/${activityId}/telemetry`, accessToken);
}

export async function getWorkoutDetection(accessToken: string, activityId: string) {
  return authenticatedRequest<WorkoutDetectionWire>(
    `/activities/${activityId}/workout-analysis/detection`,
    accessToken,
  );
}

export async function previewWorkoutSegments(
  accessToken: string,
  activityId: string,
  segments: WorkoutSegmentWire[],
) {
  return authenticatedRequest<{ segments_preview: SegmentStatsWire[]; signature: string }>(
    `/activities/${activityId}/workout-analysis/preview`,
    accessToken,
    { method: "POST", body: JSON.stringify({ segments }) },
    (_status, code) => (code === "INVALID_WORKOUT_SEGMENTS" ? "分段設定不正確" : "無法更新分段數據"),
  );
}

export async function analyseWorkout(
  accessToken: string,
  activityId: string,
  payload: {
    segments: WorkoutSegmentWire[];
    session_type: WorkoutSessionType;
    target_pace_s_per_km: number | null;
  },
) {
  return authenticatedRequest<WorkoutAnalysisWire>(
    `/activities/${activityId}/workout-analysis`,
    accessToken,
    { method: "POST", body: JSON.stringify(payload) },
    (_status, code) => (code === "INVALID_WORKOUT_SEGMENTS" ? "分段設定不正確，請檢查後再試" : "分析失敗，請稍後再試"),
  );
}

export async function updateHeartRateSettings(
  accessToken: string,
  settings: { max_hr_bpm: number | null; resting_hr_bpm: number | null; birth_year: number | null },
) {
  return authenticatedRequest<ProfileWireResponse>("/profile", accessToken, {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}

export interface PrescriptionParseWire {
  prescription: PrescriptionWire | null;
  problems: string[];
  alignment_issues: string[];
  title: string | null;
}

export async function parsePrescription(accessToken: string, activityId: string, text: string) {
  return authenticatedRequest<PrescriptionParseWire>(
    `/activities/${activityId}/prescription/parse`,
    accessToken,
    { method: "POST", body: JSON.stringify({ text }) },
    () => "無法解析課表，請稍後再試",
  );
}

export async function savePrescription(
  accessToken: string,
  activityId: string,
  rawText: string | null,
  blocks: PrescriptionBlockWire[],
) {
  return authenticatedRequest<{ prescription: PrescriptionWire }>(
    `/activities/${activityId}/prescription`,
    accessToken,
    {
      method: "PUT",
      body: JSON.stringify({
        raw_text: rawText,
        blocks: blocks.map(({ reps, distance_m, duration_s, targets_s_per_km, rest_s, rest_after_s }) => ({
          reps, distance_m, duration_s, targets_s_per_km, rest_s, rest_after_s: rest_after_s ?? null,
        })),
      }),
    },
    (_status, code) => (code === "INVALID_WORKOUT_SEGMENTS" ? "課表內容不正確" : "儲存課表失敗"),
  );
}

export async function deletePrescription(accessToken: string, activityId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/activities/${activityId}/prescription`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new ApiError(res.status, `HTTP_${res.status}`, "清除課表失敗");
}

/* ---------------- Team chat (backend/app/routes/chat.py) ---------------- */

export interface ChatRoomWire {
  id: string;
  kind: "team" | "direct";
  team_id: string;
  title: string;
  athlete_id: string | null;
  my_role: string;
  unread: number;
  last_message: string | null;
  last_at: string | null;
}

export interface ChatMessageWire {
  id: string;
  sender_kind: "user" | "ai" | "system";
  sender_id: string | null;
  sender_name: string;
  sender_is_coach: boolean;
  mine: boolean;
  body: string;
  retracted: boolean;
  mentions_ai: boolean;
  ai_state: "pending" | "done" | "failed" | null;
  payload: { batch_id?: string; kind?: string; revoked?: boolean; reply_to?: string; card_id?: string }
    & Partial<Omit<CoachSuggestionPayload, "kind">>;
  created_at: string;
}

/** An AI 健康教練 suggestion an athlete sent to the coach (backend/app/coach_handoff.py). */
export interface CoachSuggestionPayload {
  kind: "coach_suggestion";
  proposal_id: string;
  date: string;
  label: string;
  candidate: { workout_type: string; duration_minutes: number; distance_km: number; running_allowed: boolean };
  coach_assigned: string[];
}

export interface PlanBlockWire {
  reps: number;
  distance_m: number | null;
  duration_s: number | null;
  target_s_per_km: number | null;
  target_mode: "exact" | "max";
  target_text: string | null;
  rest_s: number | null;
  rest_after_s: number | null;
}

export interface PlanItemWire {
  type: "run" | "strength" | "core";
  kind?: string;
  title: string;
  content?: string;
  variants?: Partial<Record<"all" | "male" | "female", PlanBlockWire[]>>;
}

export interface PlanDayWire {
  key: string;
  date: string | null;
  date_hint: string;
  source: string;
  items: PlanItemWire[];
  problems: string[];
  removed: boolean;
  edited?: boolean;
}

export interface PlanCardPayload {
  plan: { days: PlanDayWire[]; model?: string };
  athletes: { id: string; name: string; sex: string | null; selected: boolean }[];
  source_text: string;
  today: string;
}

export interface BodyReportPayload {
  body_part: string | null;
  pain_score: number | null;
  severity_band: "NONE" | "MILD" | "MODERATE" | "SEVERE" | null;
  description: string;
  red_flags: Record<string, boolean>;
  triage: { urgency: "EMERGENCY" | "PROMPT_CLINICIAN" | "SELF_CARE_NEXT_STEP"; next_step: string; flags: string[];
            running_allowed: boolean };
  quote: string;
}

export interface PlanPreviewWire {
  rows: { key: string; date: string | null;
          entries: { athlete_id: string; name: string; status: "new" | "overwrite" | "skip_completed" | "need_date";
                     items: PlanPreviewItemWire[] }[] }[];
}

/** One plan item as it will be written for one athlete (their sex's variant). */
export interface PlanPreviewItemWire {
  title: string;
  summary: string | null;
  missing_variant: boolean;
  blocks?: PlanBlockWire[];
  /** the assigned_workouts row confirming writes; null = nothing (no variant) */
  record?: {
    title: string; duration_minutes: number; intensity_label: string;
    structure: unknown[]; tracked: boolean; notes: string | null;
  } | null;
}

export interface ChatCardWire {
  id: string;
  kind: "plan" | "body_report";
  status: "pending" | "confirmed" | "dismissed" | "cancelled";
  source_message_id: string;
  payload: PlanCardPayload | BodyReportPayload;
  created_at: string;
  preview?: PlanPreviewWire;
}

export async function getChatRooms(accessToken: string) {
  return authenticatedRequest<{ rooms: ChatRoomWire[]; unread_total: number }>("/chat/rooms", accessToken);
}

export async function getChatMessages(accessToken: string, roomId: string) {
  return authenticatedRequest<{ messages: ChatMessageWire[]; cards: ChatCardWire[]; is_coach: boolean;
                                 /** before this visit; null = never opened */ last_read_at: string | null }>(
    `/chat/rooms/${roomId}/messages`, accessToken);
}

export async function sendChatMessage(accessToken: string, roomId: string, body: string) {
  return authenticatedRequest<{ id: string; ai_pending: boolean }>(`/chat/rooms/${roomId}/messages`, accessToken,
    { method: "POST", body: JSON.stringify({ body }) }, () => "訊息送出失敗");
}

async function chatPost(accessToken: string, path: string, body?: unknown): Promise<Response> {
  return fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function markChatRead(accessToken: string, roomId: string): Promise<void> {
  await chatPost(accessToken, `/chat/rooms/${roomId}/read`);
}

export async function retractChatMessage(accessToken: string, messageId: string): Promise<void> {
  const res = await chatPost(accessToken, `/chat/messages/${messageId}/retract`);
  if (!res.ok) throw new ApiError(res.status, `HTTP_${res.status}`, "收回失敗");
}

export async function editChatCard(accessToken: string, cardId: string, edit: Record<string, unknown>) {
  return authenticatedRequest<ChatCardWire>(`/chat/cards/${cardId}`, accessToken,
    { method: "PUT", body: JSON.stringify(edit) }, () => "卡片更新失敗");
}

async function chatAction<T>(accessToken: string, path: string, forbidden: string): Promise<T> {
  const res = await chatPost(accessToken, path);
  if (!res.ok) {
    const body = await safeJson(res);
    const detail = (body?.detail ?? {}) as { reason?: string };
    throw new ApiError(res.status, String(body?.error ?? `HTTP_${res.status}`),
      res.status === 403 ? forbidden : detail.reason ?? `操作失敗（${res.status}）`);
  }
  return (res.status === 204 ? null : await res.json()) as T;
}

export async function confirmPlanCard(accessToken: string, cardId: string) {
  return chatAction<{ batch_id: string; dates: string[]; created: number; skipped: string[] }>(
    accessToken, `/chat/cards/${cardId}/confirm-plan`, "排課需要教練權限：請先切換到教練模式（輸入驗證碼）再確認");
}

export async function confirmReportCard(accessToken: string, cardId: string) {
  return chatAction<{ injury_report_id: string | null }>(accessToken, `/chat/cards/${cardId}/confirm-report`, "沒有權限");
}

export async function dismissChatCard(accessToken: string, cardId: string) {
  return chatAction<null>(accessToken, `/chat/cards/${cardId}/dismiss`, "沒有權限");
}

/** Coach only: turn a Coach Suggestion into a plan card of their own, confirmed like any plan. */
export async function scheduleSuggestion(accessToken: string, messageId: string) {
  return chatAction<ChatCardWire>(accessToken, `/chat/messages/${messageId}/schedule-suggestion`, "只有教練可以排課");
}

export async function revokePlanBatch(accessToken: string, batchId: string) {
  return chatAction<{ removed: number; kept: number }>(accessToken, `/chat/batches/${batchId}/revoke`,
    "撤銷需要教練權限：請先切換到教練模式（輸入驗證碼）");
}

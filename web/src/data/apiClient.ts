/* Thin client for the FastAPI backend's authenticated endpoints:
 *   POST /auth/demo-login   (only when COMPETITION_DEMO_ONLY=true)
 *   POST /activities, GET /activities
 *   PUT /rest-days/{date}
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

export interface CreateActivityWirePayload {
  client_mutation_id: string;
  duration_minutes: number;
  rpe: number;
  performed_at: string;
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

/* ---------------- shared authenticated-request seam ----------------
 * Every authenticated call (create/history/rest-day/trend) shares the same
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
    throw new ApiError(
      res.status,
      code,
      describeError ? describeError(res.status, code) : `請求失敗（${res.status}）`,
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

export interface RestDayWireResponse {
  date: string;
  confirmed: boolean;
}

export async function setRestDay(
  accessToken: string,
  date: string,
  confirmed: boolean,
): Promise<RestDayWireResponse> {
  return authenticatedRequest<RestDayWireResponse>(
    `/rest-days/${date}`,
    accessToken,
    { method: "PUT", body: JSON.stringify({ confirmed }) },
    (status, code) => {
      if (code === "REST_DAY_CONFLICTS_WITH_ACTIVITY")
        return "這天已經有訓練紀錄，不能同時標記為休息日";
      if (status >= 500) return "伺服器暫時無法回應，稍後會自動重試";
      return "更新休息日失敗";
    },
  );
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
}

export async function updateProfile(
  accessToken: string,
  patch: { city?: string; timezone?: string },
): Promise<ProfileWireResponse> {
  return authenticatedRequest<ProfileWireResponse>("/profile", accessToken, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export interface WeatherWireResponse {
  state: "LIVE" | "CACHED" | "STALE" | "UNAVAILABLE";
  city: string | null;
  temperature_c: number | null;
  humidity_pct: number | null;
  observed_at: string | null;
  pace_adjustment_sec_per_km: number | null;
}

export async function getWeather(accessToken: string): Promise<WeatherWireResponse> {
  return authenticatedRequest<WeatherWireResponse>("/weather", accessToken);
}

export interface RecommendationWireResponse {
  workout_type: string;
  duration_minutes: number;
  distance_km: number | null;
  target_pace_sec_per_km: number | null;
  intensity_label: string;
  adjustment_reason_code: string;
  algorithm_version: string;
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

export async function getMyAssignedWorkouts(accessToken: string) {
  return authenticatedRequest<{ items: AssignedWorkoutWireResponse[] }>(
    "/me/assigned-workouts",
    accessToken,
  );
}

/* Thin client for the FastAPI backend's authenticated endpoints:
 *   POST /auth/demo-login   (only when COMPETITION_DEMO_ONLY=true)
 *   POST /activities, GET /activities
 *   PUT /rest-days/{date}
 *   GET /training-load/trend
 *
 * Weather, the LLM-guided recommendation, coach views, and everything else
 * in this app still runs on demo data — those endpoints do not exist yet,
 * and this file does not pretend otherwise.
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

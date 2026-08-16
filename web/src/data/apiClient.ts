/* Thin client for the two endpoints the FastAPI backend actually serves:
 *   POST /auth/demo-login   (only when COMPETITION_DEMO_ONLY=true)
 *   POST /activities
 *
 * Everything else in this app runs on demo data — those endpoints do not
 * exist yet, and this file does not pretend otherwise.
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

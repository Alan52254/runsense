import { API_BASE_URL } from './config';
import { generateUuidV4 } from './uuid';
import type { ActivityDeviceMetrics } from './activityMetrics';

export interface DemoLoginResponse {
  access_token: string;
  expires_at: string;
}

export interface ActivityResponse {
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
  distance_km: number | null;
  device_metrics: ActivityDeviceMetrics;
  structure: Array<Record<string, unknown>>;
}

export class ApiError extends Error {
  // Distinguishes a server-side rejection (validation, auth) from a
  // network/transport failure -- see spec.md's two distinct failure scenarios.
  kind: 'rejected' | 'network';
  status?: number;
  body?: unknown;

  constructor(kind: 'rejected' | 'network', message: string, status?: number, body?: unknown) {
    super(message);
    this.kind = kind;
    this.status = status;
    this.body = body;
  }
}

async function parseJsonSafely(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function deriveErrorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    return JSON.stringify((body as { detail: unknown }).detail);
  }
  if (body && typeof body === 'object' && 'error' in body) {
    return String((body as { error: unknown }).error);
  }
  return `Request rejected (${status}).`;
}

// Shared shape for every authenticated JSON request this module makes.
// Not exported: this is an internal seam, not part of the module's public
// interface -- callers get typed functions (getActivityHistory, etc.),
// never this helper directly.
async function authenticatedRequest<T>(
  path: string,
  token: string,
  init?: RequestInit
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        Authorization: `Bearer ${token}`,
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError('network', 'Could not reach the server.');
  }

  const body = await parseJsonSafely(response);
  if (!response.ok) {
    throw new ApiError('rejected', deriveErrorMessage(body, response.status), response.status, body);
  }
  return body as T;
}

export async function demoLogin(email: string, password: string): Promise<DemoLoginResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/auth/demo-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  } catch (err) {
    throw new ApiError('network', 'Could not reach the server.');
  }

  const body = await parseJsonSafely(response);
  if (!response.ok) {
    throw new ApiError('rejected', 'Invalid email or password.', response.status, body);
  }
  return body as DemoLoginResponse;
}

export interface CreateActivityInput {
  durationMinutes: number;
  rpe: number;
}

export async function createActivity(
  token: string,
  input: CreateActivityInput
): Promise<ActivityResponse> {
  return authenticatedRequest<ActivityResponse>('/activities', token, {
    method: 'POST',
    body: JSON.stringify({
      client_mutation_id: generateUuidV4(),
      duration_minutes: input.durationMinutes,
      rpe: input.rpe,
      performed_at: new Date().toISOString(),
    }),
  });
}

// --- Activity history (mobile-activity-history-ui) ---

export interface ActivityHistoryResponse {
  items: ActivityResponse[];
  next_cursor: string | null;
}

export interface GetActivityHistoryOptions {
  cursor?: string | null;
  limit?: number;
}

export async function getActivityHistory(
  token: string,
  options: GetActivityHistoryOptions = {}
): Promise<ActivityHistoryResponse> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  if (options.cursor) params.set('cursor', options.cursor);
  const query = params.toString();
  return authenticatedRequest<ActivityHistoryResponse>(
    `/activities${query ? `?${query}` : ''}`,
    token
  );
}

// --- Rest days (mobile-rest-day-ui) ---

export interface RestDayResponse {
  date: string;
  confirmed: boolean;
}

export async function setRestDay(
  token: string,
  date: string,
  confirmed: boolean
): Promise<RestDayResponse> {
  return authenticatedRequest<RestDayResponse>(`/rest-days/${date}`, token, {
    method: 'PUT',
    body: JSON.stringify({ confirmed }),
  });
}

// --- Training load trend (mobile-training-load-trend-ui) ---

export interface TrainingLoadPoint {
  date: string;
  session_load: number;
  acute_load: number;
  chronic_load: number;
  load_ratio: number | null;
  data_quality: 'SUFFICIENT' | 'LOW' | 'INSUFFICIENT';
  observation_days: number;
  algorithm_version: string;
  schema_version: number;
  computed_at: string;
  input_snapshot_hash: string;
}

export interface TrainingLoadSeries {
  unit: string;
  source_metric: string;
  points: TrainingLoadPoint[];
}

export interface TrainingLoadTrendResponse {
  start_date: string;
  end_date: string;
  series: TrainingLoadSeries[];
}

export async function getTrainingLoadTrend(
  token: string,
  endDate?: string
): Promise<TrainingLoadTrendResponse> {
  const query = endDate ? `?end_date=${endDate}` : '';
  return authenticatedRequest<TrainingLoadTrendResponse>(`/training-load/trend${query}`, token);
}

// --- Weather & Guidance ---

export interface WeatherResponse {
  state: 'LIVE' | 'CACHED' | 'STALE' | 'UNAVAILABLE';
  city: string | null;
  temperature_c: number | null;
  humidity_pct: number | null;
  observed_at: string | null;
  pace_adjustment_sec_per_km: number | null;
}

export async function getWeather(token: string): Promise<WeatherResponse> {
  return authenticatedRequest<WeatherResponse>('/weather', token);
}

export interface TodayGuidanceResponse {
  local_date: string;
  recommendation: {
    workout_type: string;
    duration_minutes: number;
    distance_km: number | null;
    target_pace_sec_per_km: number | null;
    intensity_label: string;
    adjustment_reason_code: string;
    algorithm_version: string;
  };
  tone_variant_id: string;
  tone_text: string;
  tone_reviewed_by: string;
  computed_at: string;
}

export async function getTodayGuidance(token: string): Promise<TodayGuidanceResponse> {
  return authenticatedRequest<TodayGuidanceResponse>('/guidance/today?llm_tone_enabled=true', token);
}

export type PlanWorkoutType =
  | 'REST_AND_SEEK_CARE'
  | 'REST_DAY'
  | 'RECOVERY_RUN'
  | 'EASY_RUN'
  | 'STEADY_RUN';

export interface TrainingPlanCandidate {
  candidate_id: string;
  workout_type: PlanWorkoutType;
  duration_minutes: number;
  distance_km: number;
  running_allowed: boolean;
  provenance_rule_ids: string[];
  score: number | null;
  rationale: string[];
}

export interface TrainingPlanResponse {
  local_date: string;
  ranker_version: string;
  abstained: boolean;
  abstention_reason: string | null;
  confidence: number | null;
  reason_code: string;
  inputs: {
    acute_load: number | null;
    chronic_load: number | null;
    acute_chronic_ratio: number | null;
    observation_days: number;
    temperature_c: number | null;
    weather_state: 'LIVE' | 'CACHED' | 'STALE' | 'UNAVAILABLE';
    triage_urgency: 'EMERGENCY' | 'PROMPT_CLINICIAN' | 'SELF_CARE_NEXT_STEP' | null;
  };
  feature_coverage: Record<'training_load' | 'weather' | 'injury_triage', boolean>;
  candidates: TrainingPlanCandidate[];
}

export async function getTrainingPlanToday(token: string): Promise<TrainingPlanResponse> {
  return authenticatedRequest<TrainingPlanResponse>('/training-plan/today', token);
}

export interface PlanModelReportResponse {
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
    n_days?: number;
    top_choice_match_rate?: number;
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
    n_rows: number;
    n_groups: number;
    n_queries: number;
    baseline_aggregate: Record<string, number>;
    winner_declared: boolean;
    production_ranker: string;
    note: string;
  };
  production_ranker: string;
  winner_declared: boolean;
  note: string;
}

export async function getPlanModelReport(token: string): Promise<PlanModelReportResponse> {
  return authenticatedRequest<PlanModelReportResponse>('/training-plan/model-report', token);
}

// --- Injury / body-status reports (expo-demo-parity) ---
// Shapes mirror backend/app/schemas.py CreateInjuryReportRequest /
// InjuryReportResponse. The backend enforces: a no-issue report must have
// severity NONE and no body part; an issue report must have a non-NONE
// severity and a body part.

export type SeverityBand = 'NONE' | 'MILD' | 'MODERATE' | 'SEVERE';

export interface InjuryReportResponse {
  id: string;
  athlete_id: string;
  client_mutation_id: string;
  has_issue: boolean;
  severity_band: SeverityBand;
  body_part: string | null;
  reported_at: string;
  timezone_snapshot: string;
  local_training_date: string;
  free_text: string | null;
  created_at: string;
}

export interface InjuryReportListResponse {
  items: InjuryReportResponse[];
}

export interface CreateInjuryReportInput {
  clientMutationId: string;
  hasIssue: boolean;
  severityBand: SeverityBand;
  bodyPart: string | null;
  freeText: string | null;
}

export async function createInjuryReport(
  token: string,
  input: CreateInjuryReportInput
): Promise<InjuryReportResponse> {
  return authenticatedRequest<InjuryReportResponse>('/injury-reports', token, {
    method: 'POST',
    body: JSON.stringify({
      client_mutation_id: input.clientMutationId,
      has_issue: input.hasIssue,
      severity_band: input.severityBand,
      body_part: input.bodyPart,
      free_text: input.freeText,
      reported_at: new Date().toISOString(),
    }),
  });
}

export async function getInjuryReports(token: string): Promise<InjuryReportListResponse> {
  return authenticatedRequest<InjuryReportListResponse>('/injury-reports', token);
}

export interface InjuryGuidanceResponse {
  injury_report_id: string;
  urgency: 'EMERGENCY' | 'PROMPT_CLINICIAN' | 'SELF_CARE_NEXT_STEP';
  running_allowed: boolean;
  summary: string;
  next_steps: string[];
  citations: Array<{
    evidence_id: string;
    title: string;
    publisher: string;
    source_url: string;
  }>;
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
  token: string,
  injuryReportId: string,
  flags: InjuryGuidanceFlags,
): Promise<InjuryGuidanceResponse> {
  return authenticatedRequest<InjuryGuidanceResponse>('/injury-guidance', token, {
    method: 'POST',
    body: JSON.stringify({
      injury_report_id: injuryReportId,
      chest_pain_or_breathing_difficulty: flags.chestPainOrBreathingDifficulty,
      collapse_confusion_or_extreme_heat_illness: flags.collapseConfusionOrExtremeHeatIllness,
      localized_bone_pain_worse_with_weight_bearing:
        flags.localizedBonePainWorseWithWeightBearing,
    }),
  });
}

export interface CoachChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export async function chatWithCoach(
  token: string,
  messages: CoachChatMessage[],
  bodyPart?: string,
  severityBand?: string,
): Promise<{ response: string; rag_citations?: Array<{ title: string; publisher: string; text: string; source_url: string }> }> {
  return authenticatedRequest<{ response: string; rag_citations?: Array<{ title: string; publisher: string; text: string; source_url: string }> }>(
    '/guidance/chat',
    token,
    {
      method: 'POST',
      body: JSON.stringify({
        messages,
        body_part: bodyPart,
        severity_band: severityBand,
      }),
    },
  );
}

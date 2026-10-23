/* Today view model: everything the 今日訓練 screen shows about today's plan,
 * worked out once from the workspace, with no React in sight. */

import type {
  GuidanceWireResponse,
  TrainingPlanWireResponse,
  WeatherWireResponse,
} from "../data/apiClient.ts";
import { applyPctToPace } from "./paceCalc.ts";
import type { RecommendationObject, TimeOfDayTemperatureEstimate, WeatherSnapshot, WorkoutSegment } from "./types.ts";

type Locale = "zh-TW" | "en";

function hoursApart(a: number, b: number): number {
  const d = Math.abs(a - b) % 24;
  return Math.min(d, 24 - d);
}

/** The time-of-day estimate closest to `hour` (0–24, fractional), measured
 *  around the clock so 23:30 is near 06:00 across midnight. */
export function resolveTimeOfDaySlot<T extends Pick<TimeOfDayTemperatureEstimate, "hour">>(
  slots: readonly T[],
  hour: number,
): T | null {
  if (slots.length === 0) return null;
  return slots.reduce((best, slot) => (hoursApart(slot.hour, hour) < hoursApart(best.hour, hour) ? slot : best));
}

import { deriveAcwrZone, normalizeLoadWording, type AcwrZone } from "./acwr.ts";

export { deriveAcwrZone };
export type { AcwrZone };

export interface TodayInput {
  locale: Locale;
  /** False in the offline demo build: no server to ask. */
  apiConfigured: boolean;
  /** GET /training-plan/today: the ranked candidates. */
  plan: TrainingPlanWireResponse | null;
  selectedCandidateId: string | null;
  /** GET /guidance/today: a Recommendation Object with pace and segments. */
  guidance: GuidanceWireResponse | null;
  /** The workspace's own recommendation, used when there is no server. */
  offlineRecommendation: RecommendationObject;
  liveWeather: WeatherWireResponse | null;
  offlineWeather: WeatherSnapshot;
  loadRatio: number | null;
}

/** A pace in whichever shape the plan offers: one figure, or a range. */
export interface PaceShape {
  single: number | null;
  range: [number, number] | null;
}

export interface TodayWorkout {
  title: string;
  durationMinutes: number;
  distanceKm: number | null;
  targetPaceSecPerKm: number | null;
  segments: WorkoutSegment[];
}

export interface TodaySlot extends TimeOfDayTemperatureEstimate {
  pace: PaceShape;
}

export interface RankedCandidateRow {
  id: string;
  label: string;
  durationMinutes: number;
  distanceKm: number;
  score: number | null;
  /** 1-based place; tied scores share a place (1, 1, 3). */
  rank: number;
  /** The score as 適合度 0–100; null when unscored. */
  fit: number | null;
  /** What this kind of workout does, so every row says something of its own. */
  purpose: string;
  /** The server's reason for this row; null when every row has the same one
   *  (then it is rankingSharedReason, said once). */
  rationale: string | null;
  /** First place with no tie: only then is it 首選. */
  isTop: boolean;
  isSelected: boolean;
}

export interface TodayViewModel {
  /** READY: pace and segments came from the server (the ranked candidate's
   *  rule-derived pace, or the Recommendation Object), or the day is a rest
   *  day, which needs none.
   *  FALLBACK: the server named a workout but gave no pace for it; the
   *  screen then shows no figure rather than inventing one. */
  planStatus: "READY" | "FALLBACK";
  /** Where the pace figures came from. "rule-default" is still the server's,
   *  from its reviewed per-type rule because the Athlete has too few easy runs
   *  to anchor a personal pace; "none" means no figures. */
  paceSource: "server" | "rule-default" | "none";
  isRestDay: boolean;
  /** The ranked candidate shown in the hero, if the ranker supplied any. */
  activeCandidateId: string | null;
  ranking: RankedCandidateRow[];
  /** Why the ranker ordered them so, as a sentence; null if unknown. */
  rankingReason: string | null;
  /** The server's reason when every candidate carries the same one. */
  rankingSharedReason: string | null;
  workout: TodayWorkout;
  weather: WeatherSnapshot;
  climate: {
    /** % speed lost now, against a typical early evening in this city. */
    speedLossPct: number;
    nowPace: PaceShape;
    /** Seconds/km the weather adds to the point pace right now. */
    paceAdjustmentSec: number;
    slots: TodaySlot[];
    activeSlot: TodaySlot | null;
    /** The pace the hero shows: the active slot's, else now's. */
    heroPace: PaceShape;
    /** The speed loss behind heroPace, so the pill's words and pace agree. */
    heroPct: number;
    /** The slot heroPace is for; null when it is now. */
    heroSlot: TimeOfDayTemperatureEstimate["label"] | null;
  };
  acwr: { ratio: number | null; zone: AcwrZone | null };
}

const CITY_UNSET: Record<Locale, string> = { "zh-TW": "未設定城市", en: "City not set" };

function resolveWeather(input: TodayInput): WeatherSnapshot {
  const live = input.liveWeather;
  if (!input.apiConfigured || !live) return input.offlineWeather;
  return {
    state: live.state,
    city: live.city ?? CITY_UNSET[input.locale],
    temperatureC: live.temperature_c,
    humidityPct: live.humidity_pct,
    observedAtUtc: live.observed_at,
    speedLossPct: live.speed_loss_pct,
    speedLossPctUnadjusted: live.speed_loss_pct_unadjusted,
    speedLossPctRelativeToNormal: live.speed_loss_pct_relative_to_normal,
    climateNormalTemperatureC: live.climate_normal_temperature_c,
    climateNormalReferenceC: live.climate_normal_reference_c,
    timeOfDayEstimates: (live.time_of_day_estimates ?? []).map((e) => ({
      label: e.label,
      hour: e.hour,
      temperatureC: e.temperature_c,
      speedLossPct: e.speed_loss_pct,
    })),
  };
}

type PlanCandidate = TrainingPlanWireResponse["candidates"][number];

const WORKOUT_TYPE_LABEL: Record<string, Record<Locale, string>> = {
  REST_DAY: { "zh-TW": "休息日", en: "Rest Day" },
  REST_AND_SEEK_CARE: { "zh-TW": "休息並尋求專業評估", en: "Rest and seek care" },
  RECOVERY_RUN: { "zh-TW": "恢復跑", en: "Recovery Run" },
  EASY_RUN: { "zh-TW": "輕鬆跑", en: "Easy Run" },
  STEADY_RUN: { "zh-TW": "節奏/穩定跑", en: "Steady Run" },
};

const WORKOUT_PURPOSE: Record<string, Record<Locale, string>> = {
  REST_DAY: { "zh-TW": "不跑步，讓身體完整恢復", en: "No running; full recovery" },
  REST_AND_SEEK_CARE: { "zh-TW": "暫停跑步，先請專業人員評估", en: "Pause running and get assessed first" },
  RECOVERY_RUN: { "zh-TW": "短而輕鬆，以恢復為主", en: "Short and easy, for recovery" },
  EASY_RUN: { "zh-TW": "低強度累積有氧量", en: "Builds aerobic volume at low effort" },
  STEADY_RUN: { "zh-TW": "中等強度，訓練刺激較多", en: "Moderate effort, more training stimulus" },
};

function workoutTypeLabel(workoutType: string, locale: Locale): string {
  return WORKOUT_TYPE_LABEL[workoutType]?.[locale] ?? (locale === "en" ? "Daily Plan" : "今日課表");
}

const REASON_TEXT: Record<string, Record<Locale, string>> = {
  LOAD_ELEVATED_FAVOR_RECOVERY: { "zh-TW": "ACWR 負荷比高於安全區間，偏好較輕的訓練與充分休息", en: "ACWR above safe range — favor lighter training / rest" },
  LOAD_REDUCED_ADD_STIMULUS: { "zh-TW": "ACWR 負荷比低於安全區間，可加入適度刺激", en: "ACWR below safe range — room for stimulus" },
  STEADY_STATE: { "zh-TW": "ACWR 負荷比在安全區間內，維持一般有氧訓練", en: "Load steady — hold aerobic work" },
  SELF_CARE_LIMIT_INTENSITY: { "zh-TW": "自我照護模式，適度放鬆恢復", en: "Self-care triage — intensity capped" },
  TRIAGE_BLOCKED: { "zh-TW": "身體回報需注意，建議暫緩跑步", en: "Rest recommended based on body feedback" },
  COLD_START_ABSTAIN: { "zh-TW": "觀測資料累積中，採保守建議", en: "Low observation history — conservative order" },
};

const REST_TYPES = new Set(["REST_DAY", "REST_AND_SEEK_CARE", "休息日"]);

type PlannedSegment = NonNullable<PlanCandidate["segments"]>[number];

function segmentFromWire(s: PlannedSegment): WorkoutSegment {
  return {
    id: s.id,
    kind: s.kind as WorkoutSegment["kind"],
    label: s.label,
    distanceMeters: s.distance_meters ?? undefined,
    durationSeconds: s.duration_seconds ?? undefined,
    repetitions: s.repetitions ?? undefined,
    targetPaceSecPerKm: s.target_pace_sec_per_km,
    targetPaceRangeSecPerKm: s.target_pace_range_sec_per_km
      ? [s.target_pace_range_sec_per_km[0]!, s.target_pace_range_sec_per_km[1]!]
      : null,
    afterRepetition: s.after_repetition ?? undefined,
  };
}

/** A ranked candidate as a workout, with exactly the pace and segments the
 *  server worked out for it -- none when the server sent none. */
function candidateWorkout(c: PlanCandidate, locale: Locale): TodayWorkout {
  return {
    title: workoutTypeLabel(c.workout_type, locale),
    durationMinutes: c.duration_minutes,
    distanceKm: c.distance_km,
    targetPaceSecPerKm: c.target_pace_s_per_km ?? null,
    segments: (c.segments ?? []).map(segmentFromWire),
  };
}

function rationaleText(c: PlanCandidate, locale: Locale): string {
  const text = c.rationale
    ?.map((r) => normalizeLoadWording(r.replace("SELF_CARE_LIMIT_INTENSITY", "自我照護模式").replace("自我照護分流", "適度照護修復")))
    .join("；");
  return text || (locale === "en" ? "No additional explanation" : "暫無補充說明");
}

function guidanceWorkout(guidance: GuidanceWireResponse): TodayWorkout {
  const r = guidance.recommendation;
  return {
    title: r.workout_type,
    durationMinutes: r.duration_minutes,
    distanceKm: r.distance_km,
    targetPaceSecPerKm: r.target_pace_sec_per_km,
    segments: (r.segments ?? []).map(segmentFromWire),
  };
}

function offlineWorkout(r: RecommendationObject): TodayWorkout {
  return {
    title: r.workoutType,
    durationMinutes: r.durationMinutes,
    distanceKm: r.distanceKm,
    targetPaceSecPerKm: r.targetPaceSecPerKm,
    segments: r.segments ?? [],
  };
}

function hasPace(workout: TodayWorkout): boolean {
  return (
    workout.targetPaceSecPerKm !== null ||
    workout.segments.some((s) => s.targetPaceSecPerKm || s.targetPaceRangeSecPerKm)
  );
}

/** The plan's pace after `pct` % speed loss. The point pace when the plan
 *  has one; otherwise the main-effort segment's range, so a plan that only
 *  publishes a range still gets a real figure rather than an invented point. */
function paceAt(workout: TodayWorkout, pct: number): PaceShape {
  if (workout.targetPaceSecPerKm) {
    return { single: applyPctToPace(workout.targetPaceSecPerKm, pct), range: null };
  }
  const range = workout.segments.find((s) => s.kind === "work")?.targetPaceRangeSecPerKm;
  if (range) return { single: null, range: [applyPctToPace(range[0], pct), applyPctToPace(range[1], pct)] };
  return { single: null, range: null };
}

/** Places for scores in ranked order, tied scores sharing a place: 1, 1, 3. */
function competitionRanks(scores: (number | null)[]): number[] {
  return scores.map((score, i) => {
    if (score === null) return i + 1;
    const first = scores.findIndex((s) => s === score);
    return first + 1;
  });
}

export function deriveTodayViewModel(input: TodayInput, now: Date): TodayViewModel {
  const { locale } = input;
  const weather = resolveWeather(input);
  const candidates = input.plan?.candidates ?? [];
  const active =
    candidates.find((c) => c.candidate_id === input.selectedCandidateId) ?? candidates[0] ?? null;

  let workout: TodayWorkout;
  let paceSource: TodayViewModel["paceSource"];
  let isRestDay: boolean;
  if (active) {
    workout = candidateWorkout(active, locale);
    isRestDay = REST_TYPES.has(active.workout_type);
    paceSource = !hasPace(workout) ? "none" : active.pace_source === "rule_default" ? "rule-default" : "server";
  } else {
    workout =
      input.apiConfigured && input.guidance ? guidanceWorkout(input.guidance) : offlineWorkout(input.offlineRecommendation);
    isRestDay =
      REST_TYPES.has(input.guidance?.recommendation.workout_type ?? "") ||
      REST_TYPES.has(input.offlineRecommendation.workoutType);
    paceSource = hasPace(workout) ? "server" : "none";
  }

  const speedLossPct = weather.speedLossPctRelativeToNormal ?? 0;
  const nowPace = paceAt(workout, speedLossPct);
  const slots = weather.timeOfDayEstimates.map((slot) => ({ ...slot, pace: paceAt(workout, slot.speedLossPct) }));
  const activeSlot = resolveTimeOfDaySlot(slots, now.getHours() + now.getMinutes() / 60);
  const reasonCode = input.plan?.reason_code;
  const rationales = candidates.map((c) => rationaleText(c, locale));
  const sharedReason = rationales.length > 1 && rationales.every((r) => r === rationales[0]) ? rationales[0]! : null;
  const ranks = competitionRanks(candidates.map((c) => c.score));
  const topIsClear = ranks.length > 0 && ranks.filter((r) => r === 1).length === 1;

  return {
    planStatus: isRestDay || paceSource !== "none" ? "READY" : "FALLBACK",
    paceSource,
    isRestDay,
    activeCandidateId: active?.candidate_id ?? null,
    ranking: candidates.map((c, i) => ({
      id: c.candidate_id,
      label: workoutTypeLabel(c.workout_type, locale),
      durationMinutes: c.duration_minutes,
      distanceKm: c.distance_km,
      score: c.score,
      rank: ranks[i]!,
      fit: c.score === null ? null : Math.round(c.score * 100),
      purpose: WORKOUT_PURPOSE[c.workout_type]?.[locale] ?? "",
      rationale: sharedReason === null ? rationales[i]! : null,
      isTop: i === 0 && topIsClear && c.score !== null,
      isSelected: c === active,
    })),
    rankingReason: (reasonCode && REASON_TEXT[reasonCode]?.[locale]) || null,
    rankingSharedReason: sharedReason,
    workout,
    weather,
    climate: {
      speedLossPct,
      nowPace,
      paceAdjustmentSec:
        nowPace.single !== null && workout.targetPaceSecPerKm
          ? Math.round(nowPace.single - workout.targetPaceSecPerKm)
          : 0,
      slots,
      activeSlot,
      heroPace: activeSlot ? activeSlot.pace : nowPace,
      heroPct: activeSlot ? activeSlot.speedLossPct : speedLossPct,
      heroSlot: activeSlot ? activeSlot.label : null,
    },
    acwr: { ratio: input.loadRatio, zone: deriveAcwrZone(input.loadRatio) },
  };
}

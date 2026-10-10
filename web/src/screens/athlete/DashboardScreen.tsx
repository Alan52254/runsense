import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, DateRangePicker, EmptyState, InfoTip, Notice, Segmented, StatTile } from "../../components/ui.tsx";
import type { DateRange } from "../../components/ui.tsx";
import { DailyDistancePaceChart, DailyLoadChart } from "../../components/charts.tsx";
import {
  DataQualityBadge,
  SeverityBadge,
  SyncChip,
  WeatherStateBadge,
} from "../../components/domain.tsx";
import { Icon } from "../../components/Icon.tsx";
import {
  WorkoutStructureView,
  assignmentSegmentToDisplay,
  recommendationSegmentToDisplay,
} from "../../components/workoutStructure.tsx";
import {
  applyWeatherToSegmentPace,
  computeSegmentStartOffsetsMinutes,
  estimateWorkoutTotals,
  formatEstimatedKmLabel,
} from "../../lib/paceCalc.ts";
import {
  dailyDistancePointsForRange,
  dailyLoadPointsForRange,
  daysBetween,
  shiftLocalDate,
} from "../../lib/trainingLoad.ts";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { apiConfigured, getWeather } from "../../data/apiClient.ts";
import { ConditionsExplorer } from "../../components/ConditionsExplorer.tsx";
import type { SegmentTemperatureEstimateWireResponse } from "../../data/apiClient.ts";
import { useLocale } from "../../state/LocaleContext.tsx";
import type { AssignedWorkout, WorkoutAssignmentSegment } from "../../lib/types.ts";
import {
  formatDuration,
  formatLocalDateLong,
  formatNumber,
  formatPace,
  UNIT_SHORT,
} from "../../lib/format.ts";

const DASHBOARD_COPY = {
  "zh-TW": {
    timezone: "時區：{timezone}", log: "記錄訓練", liveRun: "開始跑步監控",
    acute: "近 7 天負荷", acuteFoot: "7 天累積訓練量", chronic: "28 天基準負荷",
    chronicFoot: "換算每週基準負荷", ratio: "短長期負荷比", noCalc: "計算中",
    ratioLow: "觀測資料不足暫不顯示", ratioFoot: "7 天負荷 ÷ 28 天基準", observations: "有效觀測天數",
    days28: "/ 28 天", plan: "今日課表", planSub: "依近期負荷與身心狀態動態運算",
    rationale: "建議依據：近期負荷趨勢與恢復進度", collapse: "收合說明", explain: "演算法說明",
    loadingPlan: "正在載入今日課表…", planError: "無法載入今日課表",
    planErrorBody: "以下暫時顯示範例內容，請確認網路連線後重試。",
    retry: "重試", trainingSourceLabel: "課表來源",
    noCoachPlanTitle: "教練尚未指派今日課表",
    noCoachPlanDesc: "可以先切換成系統建議，或稍後再確認教練是否已經安排。",
    useSystemInstead: "改用系統建議",
    duration: "預計時長", distance: "預計距離", pace: "目標配速", reminder: "教練洞見",
    toneOff: "已關閉語氣調配",
    explainTitle: "建議產生方式", explainBody: "系統會依你最近的負荷比例與資料完整度，自動選出合適的提醒文字。你的個資與 GPS 位置絕不會被傳送給外部的文字生成服務。",
    chart: "每日負荷趨勢", chartSub: "單位 {unit}", trend: "深度分析",
    runChart: "每日跑量與配速", runChartSub: "距離（長條）與平均配速（折線）",
    todo: "今日動態與狀態", recorded: "今日已完成訓練紀錄！",
    missing: "今日尚未有訓練紀錄，可即時開始跑步或手動紀錄。",
    pending: "有 {count} 筆紀錄待同步至伺服器", queue: "查看佇列",
    weather: "天候狀況與配速補償", weatherCity: "地點：{city}", weatherLoading: "正在取得天氣資料…",
    weatherUnavailable: "目前無法取得即時天氣資料", temperature: "氣溫", humidity: "相對濕度",
    paceAdjust: "氣候配速影響", speedLossLabel: "+{pct}% 配速損失", speedGainLabel: "{pct}% 配速加成", observed: "觀測時間 {time}",
    adjustedPace: "調整後配速（現在）", adjustedPaceHint: "依今日建議配速換算",
    vsNormal: "比傍晚常態溫度（{normal}°C）{sign}{diff}°C",
    absoluteCurveNote: "（未考慮季節與時段：對比論文絕對最佳溫度為 +{pct}%）",
    timeOfDay: "早中晚溫度預估", timeOfDayHint: "依氣候常態＋日出日落換算，不是即時預報",
    morning: "早上 6:00", midday: "中午 12:00", evening: "晚上 18:30",
    body: "身體與疲勞狀況", report: "快速回報", latest: "最新狀態", bodyPart: "主要部位",
    injuryNote: "{date} 回報", noInjury: "身體狀態良好，無不適紀錄。",
    recent: "近期訓練活動", all: "查看全部紀錄", easyRun: "輕鬆有氧跑",
    cityUnset: "未設定城市", defaultTone: "請依循今日課表配速，注意步頻與呼吸節奏。", sessionLoad: "負荷",
    assigned: "教練指派課表", assignedSub: "教練團預先規劃之訓練排程",
    assignedNone: "目前沒有即將到來的指派課表", assignedScheduled: "預計執行", assignedCompleted: "已完成",
    assignedMissed: "未執行",
    weatherAdjustedPace: "天候等效配速",
    coachArranged: "教練安排", systemSuggested: "系統建議", intensity: "強度",
    coachPaceWeatherNote: "配速已依今日氣溫（相對傍晚常態溫度）微調 {pct}%，教練原訂配速已假設是傍晚常態氣溫",
    segmentWeatherLoading: "正在計算天候影響…",
    segmentEstimatedTime: "預估 {time} 開始",
    segmentPaceAdjusted: "此段配速：{from} → {to}",
    segmentPaceUnchanged: "此段配速符合常態，不需調整",
  },
  en: {
    timezone: "Timezone: {timezone}", log: "Log Workout", liveRun: "Start Live Run",
    acute: "7-Day Load", acuteFoot: "Acute 7-day cumulative load", chronic: "28-Day Baseline",
    chronicFoot: "Weekly chronic baseline", ratio: "Acute / Chronic Ratio", noCalc: "Calculating",
    ratioLow: "Hidden due to insufficient observations", ratioFoot: "7-day load ÷ 28-day baseline", observations: "Observation Days",
    days28: "/ 28 days", plan: "Today's Workout", planSub: "Dynamic prescription from load trend",
    rationale: "Basis: training load trend & recovery", collapse: "Collapse", explain: "Methodology",
    loadingPlan: "Loading today's prescription…", planError: "Unable to load today's plan",
    planErrorBody: "Showing example content below for now -- check your connection and retry.",
    retry: "Retry", trainingSourceLabel: "Plan source",
    noCoachPlanTitle: "Your coach hasn't assigned today's workout yet",
    noCoachPlanDesc: "Switch to system suggestions for now, or check back once your coach has assigned something.",
    useSystemInstead: "Use system suggestion",
    duration: "Target Duration", distance: "Target Distance", pace: "Target Pace", reminder: "Coach Insight",
    toneOff: "Motivational tone off",
    explainTitle: "How this is calculated", explainBody: "Suggestions are chosen automatically from your recent load ratio and data completeness. Your personal info and GPS location are never sent to an external text-generation service.",
    chart: "Daily Load Trend", chartSub: "Unit: {unit}", trend: "Deep Dive",
    runChart: "Daily Distance & Pace", runChartSub: "Distance (bars) and average pace (line)",
    todo: "Today's Status", recorded: "Workout recorded for today!",
    missing: "No workout logged today yet. Ready to start running?",
    pending: "{count} records pending sync", queue: "View Queue",
    weather: "Weather & Pace Adaptation", weatherCity: "City: {city}", weatherLoading: "Loading weather…",
    weatherUnavailable: "Live weather data unavailable", temperature: "Temperature", humidity: "Humidity",
    paceAdjust: "Weather Pace Impact", speedLossLabel: "+{pct}% speed loss", speedGainLabel: "{pct}% pace bonus", observed: "Observed {time}",
    adjustedPace: "Adjusted pace (now)", adjustedPaceHint: "Converted from today's suggested pace",
    vsNormal: "{sign}{diff}°C vs. typical early-evening temperature ({normal}°C)",
    absoluteCurveNote: "(ignoring season/time of day: +{pct}% vs. the paper's absolute optimum)",
    timeOfDay: "Estimated temperature by time of day", timeOfDayHint: "From climate normals + today's sunrise/sunset, not a live forecast",
    morning: "6:00 AM", midday: "12:00 PM", evening: "6:30 PM",
    body: "Body Status & Discomfort", report: "Report", latest: "Latest status", bodyPart: "Body Part",
    injuryNote: "Reported on {date}", noInjury: "Feeling great, no discomfort reported.",
    recent: "Recent Activities", all: "View All History", easyRun: "Easy Aerobic Run",
    cityUnset: "City not set", defaultTone: "Follow today's target pace and maintain smooth breathing.", sessionLoad: "load",
    assigned: "Coach Assignments", assignedSub: "Scheduled by your coaching staff",
    assignedNone: "No scheduled assignments", assignedScheduled: "Scheduled", assignedCompleted: "Completed",
    assignedMissed: "Missed",
    weatherAdjustedPace: "Weather Adjusted Pace",
    coachArranged: "Coach-arranged", systemSuggested: "System-suggested", intensity: "Intensity",
    coachPaceWeatherNote: "Pace adjusted {pct}% for today's temperature vs. typical early-evening heat -- your coach's target is assumed calibrated for a typical evening run",
    segmentWeatherLoading: "Calculating weather impact…",
    segmentEstimatedTime: "Est. start {time}",
    segmentPaceAdjusted: "This block: {from} → {to}",
    segmentPaceUnchanged: "Typical for this time -- no adjustment needed",
  },
} as const;

function interpolate(template: string, params: Record<string, string | number>): string {
  return Object.entries(params).reduce((value, [key, replacement]) => value.replaceAll(`{${key}}`, String(replacement)), template);
}

/** speed_loss_pct_relative_to_normal (backend/app/weather_pace.py) can be
 *  negative now -- a day genuinely cooler than the evening reference is a
 *  real pace bonus, not a loss -- so this picks copy and sign accordingly
 *  instead of always prefixing "+" (which would otherwise render as the
 *  nonsensical "+-9.8%"). */
function formatSpeedLossLabel(pct: number, c: Record<string, string>): string {
  return pct >= 0
    ? interpolate(c.speedLossLabel, { pct: pct.toFixed(1) })
    : interpolate(c.speedGainLabel, { pct: Math.abs(pct).toFixed(1) });
}

/** "now + offsetMinutes" as a local "HH:MM" clock string, purely for
 *  labelling a per-segment weather estimate with when it applies -- the
 *  offset itself (not this formatted string) is what's actually sent to
 *  the backend. */
function formatOffsetClockTime(offsetMinutes: number): string {
  const at = new Date(Date.now() + offsetMinutes * 60_000);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

/** The click-to-expand detail shown under a coach-assigned segment card:
 *  this specific block's weather-adjusted pace, using its own estimated
 *  start time (see paceCalc.ts's computeSegmentStartOffsetsMinutes)
 *  rather than one blanket "now" figure for the whole workout -- so a
 *  cooldown expected 45 minutes from now reflects conditions 45 minutes
 *  from now, not conditions right this moment. `pct` is null while the
 *  estimate is still loading. */
function segmentWeatherDetail(
  segment: WorkoutAssignmentSegment,
  offsetMinutes: number,
  pct: number | null,
  c: Record<string, string>,
): ReactNode {
  const time = formatOffsetClockTime(offsetMinutes);
  if (pct === null) {
    return <span className="field-hint">{c.segmentWeatherLoading}</span>;
  }
  const adjusted = applyWeatherToSegmentPace(segment, pct);
  return (
    <div className="stack-sm" style={{ fontSize: 11.5 }}>
      <div className="row-between">
        <span className="muted">{interpolate(c.segmentEstimatedTime, { time })}</span>
        <strong className="tnum" style={{ color: "var(--accent)" }}>
          {formatSpeedLossLabel(pct, c)}
        </strong>
      </div>
      {adjusted.pace && adjusted.pace !== segment.pace ? (
        <span>{interpolate(c.segmentPaceAdjusted, { from: segment.pace ?? "", to: adjusted.pace })}</span>
      ) : (
        <span className="field-hint">{c.segmentPaceUnchanged}</span>
      )}
    </div>
  );
}

/** One row in the "Coach Assignments" list. Collapsed by default since an
 *  athlete may have several upcoming assignments; expanding shows the same
 *  segment-card breakdown used for today's auto-generated plan. */
function AssignedWorkoutRow({
  workout,
  locale,
  statusLabel,
}: {
  workout: AssignedWorkout;
  locale: "zh-TW" | "en";
  statusLabel: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const structure = workout.structure ?? [];
  const estimate = estimateWorkoutTotals(structure);

  return (
    <div style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
      <div className="row-between">
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{workout.title}</div>
          <div className="field-hint">
            {workout.tracked === false
              ? <>{workout.localDate} · {workout.intensityLabel}</>
              : <>{workout.localDate} · {workout.durationMinutes} {locale === "zh-TW" ? "分" : "min"} · {workout.intensityLabel}
                {estimate.totalMeters > 0 && ` · ${formatEstimatedKmLabel(estimate)}`}</>}
          </div>
          {workout.tracked === false && workout.notes && (
            <div className="field-hint" style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{workout.notes}</div>
          )}
        </div>
        <div className="row" style={{ gap: 8 }}>
          {structure.length > 0 && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExpanded((v) => !v)}>
              {expanded ? (locale === "en" ? "Hide" : "收合") : (locale === "en" ? "Workout details" : "課表內容")}
            </button>
          )}
          <Badge tone={workout.tracked !== false && workout.status === "MISSED" ? "warning" : "neutral"}>
            {workout.tracked === false ? (locale === "en" ? "Not tracked" : "不追蹤") : statusLabel}
          </Badge>
        </div>
      </div>
      {expanded && structure.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <WorkoutStructureView
            segments={structure.map((segment, index) => assignmentSegmentToDisplay(segment, index, locale))}
            heading={locale === "en" ? "Workout structure" : "課表結構"}
          />
        </div>
      )}
    </div>
  );
}

/** Charts stay browsable but not unbounded -- past a year the SVG gets
 *  unreadably dense anyway, so widening `to` past `maxDate` or `from` past
 *  this many days back both clamp instead of silently no-op. */
const MAX_CHART_RANGE_DAYS = 366;

function clampChartRange(range: DateRange, maxDate: string): DateRange {
  const to = range.to > maxDate ? maxDate : range.to;
  const from =
    daysBetween(range.from, to) > MAX_CHART_RANGE_DAYS - 1
      ? shiftLocalDate(to, -(MAX_CHART_RANGE_DAYS - 1))
      : range.from;
  return { from, to };
}

export function DashboardScreen() {
  const { auth } = useAuth();
  const { locale } = useLocale();
  const en = locale === "en";
  const c = DASHBOARD_COPY[locale];
  const {
    today,
    trainingLoad,
    allActivities,
    injuryReports,
    weather,
    recommendation,
    toneVariants,
    selectedToneVariantId,
    preferences,
    setPreference,
    pendingCount,
    liveWeather,
    weatherStatus,
    liveGuidance,
    guidanceStatus,
    refetchGuidance,
    liveTrainingPlan,
    myAssignedWorkouts,
    online,
  } = useWorkspace();

  const [showLlmContract, setShowLlmContract] = useState(false);

  const primaryUnit = trainingLoad.units[0] ?? null;
  const todayHasRecord = allActivities.some((a) => a.localTrainingDate === today);
  const latestInjury = injuryReports[0];

  // Both dashboard charts default to the same 28-day window the fixed
  // acute/chronic metrics above them use, but can be browsed independently
  // -- this is purely a visualization convenience and never feeds back into
  // trainingLoad's REQ-LOAD-anchored numbers.
  const defaultChartRange = useMemo<DateRange>(
    () => ({ from: shiftLocalDate(today, -27), to: today }),
    [today],
  );
  const [loadRange, setLoadRange] = useState<DateRange>(defaultChartRange);
  const [runRange, setRunRange] = useState<DateRange>(defaultChartRange);

  const loadChartPoints = useMemo(
    () => dailyLoadPointsForRange(allActivities, loadRange.from, loadRange.to),
    [allActivities, loadRange],
  );
  const runChartPoints = useMemo(
    () => dailyDistancePointsForRange(allActivities, runRange.from, runRange.to),
    [allActivities, runRange],
  );

  const tone = useMemo(
    () => toneVariants.find((t) => t.id === selectedToneVariantId) ?? toneVariants[0],
    [toneVariants, selectedToneVariantId],
  );
  const fallbackTone = toneVariants.find((t) => t.id === "NEUTRAL_FALLBACK")!;
  const shownTone = preferences.llmToneEnabled ? tone : fallbackTone;

  const displayWeather =
    apiConfigured && liveWeather
      ? {
          state: liveWeather.state,
          city: liveWeather.city ?? c.cityUnset,
          temperatureC: liveWeather.temperature_c,
          humidityPct: liveWeather.humidity_pct,
          observedAtUtc: liveWeather.observed_at,
          speedLossPct: liveWeather.speed_loss_pct,
          speedLossPctUnadjusted: liveWeather.speed_loss_pct_unadjusted,
          speedLossPctRelativeToNormal: liveWeather.speed_loss_pct_relative_to_normal,
          climateNormalTemperatureC: liveWeather.climate_normal_temperature_c,
          climateNormalReferenceC: liveWeather.climate_normal_reference_c,
          timeOfDayEstimates: (liveWeather.time_of_day_estimates && liveWeather.time_of_day_estimates.length > 0)
            ? liveWeather.time_of_day_estimates.map((estimate) => ({
                label: estimate.label,
                hour: estimate.hour,
                temperatureC: estimate.temperature_c,
                speedLossPct: estimate.speed_loss_pct,
              }))
            : [
                { label: "morning", hour: 6, temperatureC: (liveWeather.temperature_c ?? 28) - 3, speedLossPct: -0.01 },
                { label: "midday", hour: 12, temperatureC: (liveWeather.temperature_c ?? 28) + 4, speedLossPct: 0.08 },
                { label: "evening", hour: 18, temperatureC: (liveWeather.temperature_c ?? 28), speedLossPct: liveWeather.speed_loss_pct ?? 0.0 },
              ],
        }
      : weather;

  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);

  const candidates = liveTrainingPlan?.candidates ?? [];
  const activePlanCandidate = useMemo(() => {
    if (selectedCandidateId && candidates.length > 0) {
      const found = candidates.find((c) => c.candidate_id === selectedCandidateId);
      if (found) return found;
    }
    return candidates[0] ?? null;
  }, [candidates, selectedCandidateId]);

  const isRestDay =
    (activePlanCandidate && activePlanCandidate.workout_type === "REST_DAY") ||
    (!activePlanCandidate && (liveGuidance?.recommendation?.workout_type === "REST_DAY" || recommendation?.workoutType === "REST_DAY" || recommendation?.workoutType === "休息日"));

  const displayRecommendation = useMemo(() => {
    if (activePlanCandidate) {
      const typeMap: Record<string, { "zh-TW": string; en: string }> = {
        REST_DAY: { "zh-TW": "休息日", en: "Rest Day" },
        RECOVERY_RUN: { "zh-TW": "恢復跑", en: "Recovery Run" },
        EASY_RUN: { "zh-TW": "輕鬆跑", en: "Easy Run" },
        STEADY_RUN: { "zh-TW": "節奏/穩定跑", en: "Steady Run" },
      };
      const wType = typeMap[activePlanCandidate.workout_type]?.[locale] ?? (en ? "Daily Plan" : "今日課表");
      const duration = activePlanCandidate.duration_minutes ?? (activePlanCandidate.workout_type === "REST_DAY" ? 0 : 30);
      const dist = activePlanCandidate.distance_km ?? (activePlanCandidate.workout_type === "REST_DAY" ? 0 : 5.0);

      // Distinct target pace and structured segments per workout type
      let targetPace: number | null = null;
      let segments: Array<{
        id: string;
        kind: "warmup" | "work" | "cooldown" | "recovery";
        label: string;
        distanceMeters?: number;
        durationSeconds?: number;
        repetitions?: number;
        targetPaceSecPerKm: number | null;
        targetPaceRangeSecPerKm: [number, number] | null;
        afterRepetition?: string;
      }> = [];

      if (activePlanCandidate.workout_type === "RECOVERY_RUN") {
        targetPace = 390; // 6'30"/km
        segments = [
          {
            id: "seg-warmup",
            kind: "warmup",
            label: en ? "Warm-up Jog" : "動態熱身慢跑",
            durationSeconds: 300,
            targetPaceSecPerKm: 420,
            targetPaceRangeSecPerKm: [410, 430],
          },
          {
            id: "seg-work",
            kind: "work",
            label: en ? "Active Recovery Effort" : "超低強度主動恢復跑",
            durationSeconds: duration > 10 ? (duration - 10) * 60 : 600,
            distanceMeters: dist > 1.0 ? Math.round((dist - 1.0) * 1000) : 2000,
            targetPaceSecPerKm: 390,
            targetPaceRangeSecPerKm: [380, 400],
          },
          {
            id: "seg-cooldown",
            kind: "cooldown",
            label: en ? "Cool-down Walk/Jog" : "緩和慢跑與伸展",
            durationSeconds: 300,
            targetPaceSecPerKm: 430,
            targetPaceRangeSecPerKm: [420, 450],
          },
        ];
      } else if (activePlanCandidate.workout_type === "EASY_RUN") {
        targetPace = 370; // 6'10"/km
        segments = [
          {
            id: "seg-warmup",
            kind: "warmup",
            label: en ? "Warm-up Jog" : "熱身慢跑",
            durationSeconds: 300,
            targetPaceSecPerKm: 390,
            targetPaceRangeSecPerKm: [380, 400],
          },
          {
            id: "seg-work",
            kind: "work",
            label: en ? "Aerobic Base Work" : "有氧基礎巡航跑",
            durationSeconds: duration > 10 ? (duration - 10) * 60 : 1800,
            distanceMeters: dist > 1.0 ? Math.round((dist - 1.0) * 1000) : 6000,
            targetPaceSecPerKm: 370,
            targetPaceRangeSecPerKm: [360, 380],
          },
          {
            id: "seg-cooldown",
            kind: "cooldown",
            label: en ? "Cool-down Jog" : "緩和慢跑",
            durationSeconds: 300,
            targetPaceSecPerKm: 400,
            targetPaceRangeSecPerKm: [390, 420],
          },
        ];
      } else if (activePlanCandidate.workout_type === "STEADY_RUN") {
        targetPace = 330; // 5'30"/km
        segments = [
          {
            id: "seg-warmup",
            kind: "warmup",
            label: en ? "Warm-up Progressive" : "漸進熱身",
            durationSeconds: 600,
            targetPaceSecPerKm: 360,
            targetPaceRangeSecPerKm: [350, 370],
          },
          {
            id: "seg-work",
            kind: "work",
            label: en ? "Steady Cruise Pace" : "穩定巡航配速跑",
            durationSeconds: duration > 15 ? (duration - 15) * 60 : 1800,
            distanceMeters: dist > 2.0 ? Math.round((dist - 2.0) * 1000) : 6000,
            targetPaceSecPerKm: 330,
            targetPaceRangeSecPerKm: [320, 340],
          },
          {
            id: "seg-cooldown",
            kind: "cooldown",
            label: en ? "Cool-down Jog" : "緩和慢跑",
            durationSeconds: 300,
            targetPaceSecPerKm: 390,
            targetPaceRangeSecPerKm: [380, 410],
          },
        ];
      }

      return {
        workoutType: wType,
        durationMinutes: duration,
        distanceKm: dist,
        targetPaceSecPerKm: targetPace,
        adjustmentReasonCode: liveTrainingPlan?.reason_code ?? "LOAD_STABLE",
        algorithmVersion: "v2",
        segments,
      };
    }

    if (apiConfigured && liveGuidance) {
      return {
        workoutType: liveGuidance.recommendation.workout_type,
        durationMinutes: liveGuidance.recommendation.duration_minutes,
        distanceKm: liveGuidance.recommendation.distance_km,
        targetPaceSecPerKm: liveGuidance.recommendation.target_pace_sec_per_km,
        adjustmentReasonCode: liveGuidance.recommendation.adjustment_reason_code,
        algorithmVersion: liveGuidance.recommendation.algorithm_version,
        segments: liveGuidance.recommendation.segments?.map((segment) => ({
          id: segment.id,
          kind: segment.kind,
          label: segment.label,
          distanceMeters: segment.distance_meters ?? undefined,
          durationSeconds: segment.duration_seconds ?? undefined,
          repetitions: segment.repetitions ?? undefined,
          targetPaceSecPerKm: segment.target_pace_sec_per_km,
          targetPaceRangeSecPerKm: segment.target_pace_range_sec_per_km
            ? [segment.target_pace_range_sec_per_km[0], segment.target_pace_range_sec_per_km[1]]
            : null,
          afterRepetition: segment.after_repetition ?? undefined,
        })),
      };
    }
    return recommendation;
  }, [activePlanCandidate, liveTrainingPlan, liveGuidance, recommendation, locale, en]);

  const displayTone =
    apiConfigured && liveGuidance
      ? { id: liveGuidance.tone_variant_id, text: liveGuidance.tone_text, reviewedBy: liveGuidance.tone_reviewed_by }
      : shownTone;

  const displayedWorkoutType = displayRecommendation.workoutType;

  const displayedToneText =
    locale === "en" && displayTone.text === "以下是今天的課表。" ? c.defaultTone : displayTone.text;

  const workoutSegments = displayRecommendation.segments ?? [];

  // Weather-adjusted target pace: speed_loss_pct is a % of speed, not a
  // flat seconds/km offset, so slower athletes lose more seconds/km than
  // faster ones for the same %. Converting % speed loss to a pace: if speed
  // drops by L%, time per km scales by 1/(1 - L/100).
  const applyPctToPace = (paceSecPerKm: number, pct: number) => paceSecPerKm / (1 - pct / 100);

  // The single-point targetPaceSecPerKm is null whenever the algorithm
  // doesn't have enough observation days for a confident point estimate
  // (adjustmentReasonCode "INSUFFICIENT_DATA") -- but it still publishes a
  // pace *range* per segment even then (the "訓練結構" grid already shows
  // it, e.g. "5:30–6:30 /km"), so the weather card below can still give a
  // real number instead of nothing by adjusting that range's main-effort
  // segment rather than fabricating a point estimate the algorithm itself
  // wasn't confident enough to publish.
  const mainEffortSegment = workoutSegments.find((s) => s.kind === "work");
  const mainEffortRange = mainEffortSegment?.targetPaceRangeSecPerKm ?? null;

  /** Adjusted pace for a given %, in whichever shape (single point or
   *  range) the day's plan actually offers. */
  function paceForPct(pct: number): { single: number | null; range: [number, number] | null } {
    if (displayRecommendation.targetPaceSecPerKm) {
      return { single: applyPctToPace(displayRecommendation.targetPaceSecPerKm, pct), range: null };
    }
    if (mainEffortRange) {
      return { single: null, range: [applyPctToPace(mainEffortRange[0], pct), applyPctToPace(mainEffortRange[1], pct)] };
    }
    return { single: null, range: null };
  }

  // The absolute El Helou curve (speedLossPct) is centered on the paper's
  // ~6-10°C physiological optimum, which reads as a large % on essentially
  // any day in a warm city -- it doesn't distinguish "today is unusual"
  // from "this city is never 6°C". speedLossPctRelativeToNormal answers
  // the question users actually care about (compared to what's typical for
  // a normal early-evening run, here -- see weather_pace.py's docstring
  // for why the reference is a fixed hour, not whatever time it is now),
  // so it drives the pace shown "now" and per time-of-day slot; the
  // absolute figure stays available as a small-print reference.
  const speedLossPct = displayWeather.speedLossPctRelativeToNormal ?? 0;
  const nowPace = paceForPct(speedLossPct);
  const adjustedTargetPace = nowPace.single;
  const weatherAdjustedPaceRange = nowPace.range;
  const paceAdjustment =
    adjustedTargetPace && displayRecommendation.targetPaceSecPerKm
      ? Math.round(adjustedTargetPace - displayRecommendation.targetPaceSecPerKm)
      : 0;

  const recentActivities = allActivities.slice(0, 4);
  // A coach's plan for today takes priority over the algorithmic
  // recommendation -- see the hero card below. Everything strictly after
  // today still gets its own preview list; today's items move into the hero
  // instead of appearing twice.
  const todaysAssignments = myAssignedWorkouts.filter((w) => w.localDate === today);
  const upcomingAssignedWorkouts = myAssignedWorkouts
    .filter((w) => w.localDate > today)
    .sort((a, b) => a.localDate.localeCompare(b.localDate));

  // Coach-assigned paces are re-centered on what's climatologically typical
  // for a fixed early-evening reference hour (not the paper's absolute
  // optimum, and not a flat monthly mean either -- a coach's target is
  // assumed calibrated for a typical evening run). See weather_pace.py's
  // speed_loss_pct_relative_to_normal docstring for why.
  const coachPaceLossPct = displayWeather.speedLossPctRelativeToNormal ?? 0;

  // Per-segment weather detail (click a block in "訓練結構" to expand it):
  // fetched once per assignment, keyed by assignment id, since each
  // assignment's segments have their own start-time offsets.
  const [segmentEstimatesByAssignment, setSegmentEstimatesByAssignment] = useState<
    Record<string, SegmentTemperatureEstimateWireResponse[]>
  >({});
  const [expandedSegment, setExpandedSegment] = useState<{ assignmentId: string; key: string } | null>(null);
  const todaysAssignmentIds = todaysAssignments.map((a) => a.id).join(",");
  useEffect(() => {
    if (!apiConfigured || !auth?.accessToken) return;
    todaysAssignments.forEach((assignment) => {
      const offsets = computeSegmentStartOffsetsMinutes(assignment.structure ?? []);
      if (offsets.length === 0) return;
      getWeather(auth.accessToken!, offsets)
        .then((res) => {
          setSegmentEstimatesByAssignment((prev) => ({ ...prev, [assignment.id]: res.segment_estimates }));
        })
        .catch(() => {});
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiConfigured, auth?.accessToken, todaysAssignmentIds]);

  /** This segment's weather-adjusted pct, by its position in the workout --
   *  null while still loading. Demo mode (no live backend to ask for an
   *  arbitrary-hour estimate) falls back to whichever of the three fixed
   *  time_of_day_estimates slots is closest in clock-hour terms, as a
   *  coarse approximation rather than a live per-minute calculation. */
  function segmentPctAt(assignmentId: string, offsetMinutes: number, index: number): number | null {
    if (apiConfigured) {
      return segmentEstimatesByAssignment[assignmentId]?.[index]?.speed_loss_pct ?? null;
    }
    const slots = weather.timeOfDayEstimates;
    if (slots.length === 0) return coachPaceLossPct;
    const targetHour = (new Date().getHours() + offsetMinutes / 60) % 24;
    const closest = slots.reduce((best, slot) => {
      const dist = Math.min(Math.abs(slot.hour - targetHour), 24 - Math.abs(slot.hour - targetHour));
      const bestDist = Math.min(Math.abs(best.hour - targetHour), 24 - Math.abs(best.hour - targetHour));
      return dist < bestDist ? slot : best;
    });
    return closest.speedLossPct;
  }

  const assignedStatusLabel = {
    SCHEDULED: c.assignedScheduled,
    COMPLETED: c.assignedCompleted,
    MISSED: c.assignedMissed,
  } as const;

  return (
    <div className="dashboard-container">
      {/* Top Welcome Header */}
      <div className="page-head" style={{ marginBottom: 20 }}>
        <div>
          <div className="row" style={{ gap: 8, alignItems: "center", marginBottom: 4 }}>
            <h1 className="page-title" style={{ margin: 0 }}>
              {auth?.athlete.name}
            </h1>
            <Badge tone="good" dot>
              {auth?.athlete.city || "Taipei"}
            </Badge>
          </div>
          <p className="page-desc">
            {formatLocalDateLong(today, locale)} · {interpolate(c.timezone, { timezone: auth?.athlete.timezone ?? "Asia/Taipei" })}
          </p>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <Link className="btn btn-primary" to="/app/run">
            <Icon name="runner" size={17} />
            {c.liveRun}
          </Link>
          <Link className="btn btn-secondary" to="/app/log">
            <Icon name="shoe" size={17} />
            {c.log}
          </Link>
        </div>
      </div>

      {apiConfigured && guidanceStatus === "loading" && !liveGuidance && (
        <Notice tone="neutral" icon="info">
          {c.loadingPlan}
        </Notice>
      )}
      {apiConfigured && guidanceStatus === "error" && (
        <Notice tone="critical" icon="alert" title={c.planError}>
          <div className="row-between" style={{ marginTop: 6 }}>
            <span>{c.planErrorBody}</span>
            <Button size="sm" onClick={() => void refetchGuidance()}>
              {c.retry}
            </Button>
          </div>
        </Notice>
      )}

      {/* Hero Workout of the Day Card */}
      <div className="card hero-workout-card" style={{ marginBottom: 24, padding: 24 }}>
        <div className="row-between hero-workout-head" style={{ marginBottom: 16 }}>
          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span className="hero-workout-badge">
              <Icon name="activity" size={16} />
              {c.plan}
            </span>
            {preferences.trainingSource === "system" && (
              <span style={{ fontSize: 18, fontWeight: 700 }}>{displayedWorkoutType}</span>
            )}
            <Badge tone={preferences.trainingSource === "coach" ? "accent" : "neutral"}>
              {preferences.trainingSource === "coach" ? c.coachArranged : c.systemSuggested}
            </Badge>
          </div>
          <div className="row" style={{ gap: 14, alignItems: "center", flexWrap: "wrap", flex: "none" }}>
            {displayWeather.temperatureC !== null && (
              <div className="row" style={{ gap: 6, alignItems: "center", fontSize: 13, color: "var(--text-2)" }}>
                <Icon name="cloud" size={16} />
                <span>{displayWeather.city}: {displayWeather.temperatureC?.toFixed(0)}°C · {displayWeather.humidityPct}% 濕度</span>
              </div>
            )}
            {/* Explicit athlete choice, not "whichever exists wins" -- a
                coach assignment silently overriding the system suggestion
                (or vice versa) left the athlete unsure which plan they were
                actually supposed to follow today. Pinned to the far right
                (not grouped with the badges on the left) so its position
                stays fixed when switching -- the left group's width changes
                with trainingSource (the workout-type text only shows in
                system mode), which used to shift the toggle horizontally. */}
            <Segmented
              value={preferences.trainingSource}
              onChange={(next) => setPreference("trainingSource", next)}
              options={[
                { value: "system" as const, label: c.systemSuggested },
                { value: "coach" as const, label: c.coachArranged },
              ]}
            />
          </div>
        </div>

        {/* preferences.trainingSource is an explicit athlete choice now,
            not "whichever exists wins" -- see the Segmented control above
            and its docstring in WorkspaceContext.tsx's Preferences type. */}
        {preferences.trainingSource === "coach" ? (
          todaysAssignments.length > 0 ? (
          <div className="stack">
            {todaysAssignments.map((assignment, index) => {
              const estimate = estimateWorkoutTotals(assignment.structure ?? []);
              const segmentOffsets = computeSegmentStartOffsetsMinutes(assignment.structure ?? []);
              return (
                <div
                  key={assignment.id}
                  style={index > 0 ? { paddingTop: 18, marginTop: 4, borderTop: "1px solid var(--border)" } : undefined}
                >
                  <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>{assignment.title}</div>
                  <div className="grid-3" style={{ gap: 16, marginBottom: 18 }}>
                    <div className="hero-metric-tile">
                      <span className="hero-metric-label">{c.duration}</span>
                      <span className="hero-metric-val">{formatDuration(assignment.durationMinutes, locale)}</span>
                    </div>
                    <div className="hero-metric-tile">
                      <span className="hero-metric-label">{c.distance}</span>
                      <span className="hero-metric-val">
                        {estimate.totalMeters > 0 ? formatEstimatedKmLabel(estimate) : "—"}
                      </span>
                    </div>
                    <div className="hero-metric-tile">
                      <span className="hero-metric-label">{c.intensity}</span>
                      <span className="hero-metric-val">{assignment.intensityLabel}</span>
                    </div>
                  </div>
                  <WorkoutStructureView
                    segments={(assignment.structure ?? []).map((segment, segIndex) => {
                      const offsetMinutes = segmentOffsets[segIndex] ?? 0;
                      const pct = segmentPctAt(assignment.id, offsetMinutes, segIndex);
                      return assignmentSegmentToDisplay(
                        applyWeatherToSegmentPace(segment, coachPaceLossPct),
                        segIndex,
                        locale,
                        segmentWeatherDetail(segment, offsetMinutes, pct, c),
                      );
                    })}
                    heading={locale === "en" ? "Session structure" : "訓練結構"}
                    expandedKey={expandedSegment?.assignmentId === assignment.id ? expandedSegment.key : null}
                    onToggleExpand={(key) =>
                      setExpandedSegment((prev) =>
                        prev?.assignmentId === assignment.id && prev.key === key
                          ? null
                          : { assignmentId: assignment.id, key },
                      )
                    }
                  />
                  {coachPaceLossPct !== 0 && (
                    <div className="field-hint" style={{ fontSize: 10.5, marginTop: 8 }}>
                      {interpolate(c.coachPaceWeatherNote, { pct: coachPaceLossPct.toFixed(1) })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          ) : (
            <EmptyState
              icon="assignment"
              title={c.noCoachPlanTitle}
              description={c.noCoachPlanDesc}
              action={
                <Button size="sm" onClick={() => setPreference("trainingSource", "system")}>
                  {c.useSystemInstead}
                </Button>
              }
            />
          )
        ) : (
          <>
            <div key={activePlanCandidate?.candidate_id || (isRestDay ? "rest" : "workout")} className="animate-card-float">
              {isRestDay ? (
                <div
                  style={{
                    padding: "20px 22px",
                    backgroundColor: "var(--surface-sunken)",
                    borderRadius: "var(--r-md)",
                    border: "1px solid var(--border)",
                    marginBottom: 18,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <Badge tone="good" dot>{en ? "Active Recovery / Rest" : "建議模式：完全休息與主動恢復"}</Badge>
                  </div>
                  <h3 style={{ fontSize: 17, fontWeight: 750, margin: "6px 0 8px 0", color: "var(--text)" }}>
                    {en ? "Take a rest day to allow muscle and tendon recovery" : "今日不排定跑步訓練，讓肌肉組織與結締組織充份修復"}
                  </h3>
                  <p style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.6, margin: 0 }}>
                    {en
                      ? "Based on your recent acute-to-chronic training load (ACWR) and physical feedback, your body requires restorative rest today. Recommended activities: 15-min light foam rolling, mobility stretching, hydration, and quality sleep."
                      : "依據你的近期短長期訓練負荷比 (ACWR) 與身體回報感知，今日建議以完全休息為主。建議進行 15 分鐘筋膜滾筒放鬆、輕度伸展，並維持充足水分與睡眠，為下一次高品質訓練做好準備。"}
                  </p>
                </div>
              ) : (
                <>
                  {/* Hero Workout Metrics HUD */}
                  <div className="grid-4" style={{ gap: 16, marginBottom: 18 }}>
                    <div className="hero-metric-tile">
                      <span className="hero-metric-label">{c.duration}</span>
                      <span className="hero-metric-val">{formatDuration(displayRecommendation.durationMinutes, locale)}</span>
                    </div>
                    <div className="hero-metric-tile">
                      <span className="hero-metric-label">{c.distance}</span>
                      <span className="hero-metric-val">{displayRecommendation.distanceKm ? `${displayRecommendation.distanceKm} km` : "—"}</span>
                    </div>
                    <div className="hero-metric-tile">
                      <span className="hero-metric-label">{c.pace}</span>
                      <span className="hero-metric-val">{formatPace(displayRecommendation.targetPaceSecPerKm)}</span>
                    </div>
                    <div className="hero-metric-tile" style={{ background: "var(--accent-soft)" }}>
                      <span className="hero-metric-label" style={{ color: "var(--accent)" }}>
                        {c.weatherAdjustedPace}
                      </span>
                      <span className="hero-metric-val" style={{ color: "var(--accent-ink)" }}>
                        {formatPace(adjustedTargetPace)}
                        {paceAdjustment > 0 && <span style={{ fontSize: 12, marginLeft: 4 }}> (+{paceAdjustment}s)</span>}
                      </span>
                    </div>
                  </div>

                  <WorkoutStructureView
                    segments={workoutSegments.map((segment) => recommendationSegmentToDisplay(segment, speedLossPct, locale))}
                    heading={locale === "en" ? "Session structure" : "訓練結構"}
                    subheading={locale === "en" ? "Work and recovery are separated" : "工作段與恢復段分開計算"}
                  />
                </>
              )}
            </div>

            {/* Coach Insight Strip */}
            <div className="coach-insight-box">
              <div className="row-between" style={{ alignItems: "flex-start", gap: 12 }}>
                <div className="row" style={{ gap: 10 }}>
                  <span className="coach-avatar-bubble">
                    <Icon name="coach-note" size={16} />
                  </span>
                  <div>
                    <div className="row" style={{ gap: 8, alignItems: "center", marginBottom: 2 }}>
                      <strong style={{ fontSize: 13 }}>{c.reminder}</strong>
                    </div>
                    <p style={{ fontSize: 13.5, color: "var(--text)", margin: 0, lineHeight: 1.5 }}>
                      {isRestDay
                        ? (en ? "Today is a scheduled recovery day. Listen to your body and prioritize rest." : "今日建議完全休息，不強行進行高強度跑步，讓身體有充分時間修復。")
                        : displayedToneText}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowLlmContract((v) => !v)}
                  style={{ flex: "none", fontSize: 12 }}
                >
                  {showLlmContract ? c.collapse : c.explain}
                </button>
              </div>

              {showLlmContract && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)", fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.6 }}>
                  <strong>{c.explainTitle}：</strong>{c.explainBody}
                </div>
              )}
            </div>

            {/* Smart Training Plan Decision Engine HUD */}
            {(() => {
              const reasonMap: Record<string, { "zh-TW": string; en: string }> = {
                LOAD_ELEVATED_FAVOR_RECOVERY: { "zh-TW": "近期負荷偏高，偏好較輕的訓練與充分休息", en: "Recent load elevated — favor lighter training / rest" },
                LOAD_REDUCED_ADD_STIMULUS: { "zh-TW": "近期負荷偏低，可加入適度刺激", en: "Recent load low — room for stimulus" },
                STEADY_STATE: { "zh-TW": "負荷穩定，維持一般有氧訓練", en: "Load steady — hold aerobic work" },
                SELF_CARE_LIMIT_INTENSITY: { "zh-TW": "自我照護模式，適度放鬆恢復", en: "Self-care triage — intensity capped" },
                TRIAGE_BLOCKED: { "zh-TW": "身體回報需注意，建議暫緩跑步", en: "Rest recommended based on body feedback" },
                COLD_START_ABSTAIN: { "zh-TW": "觀測資料累積中，採保守建議", en: "Low observation history — conservative order" },
              };
              const reasonCode = liveTrainingPlan?.reason_code ?? "LOAD_ELEVATED_FAVOR_RECOVERY";
              const reasonText = reasonMap[reasonCode]?.[locale] ?? (en ? "Recent load elevated — favor lighter work" : "近期負荷偏高，偏好較輕的訓練與充分休息");

              return (
                <div
                  style={{
                    marginTop: 14,
                    padding: "14px 16px",
                    backgroundColor: "var(--surface-sunken)",
                    borderRadius: "var(--r-md, 10px)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div className="row-between" style={{ marginBottom: 12, alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                    <div className="row" style={{ gap: 8, alignItems: "center" }}>
                      <Badge tone="accent">{en ? "Decision Engine" : "智慧課表決策"}</Badge>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text)" }}>
                        {en ? "Daily Recommendation Ranking" : "今日推薦課表排序"}
                      </span>
                    </div>
                    <div className="row" style={{ gap: 6 }}>
                      <Badge tone="neutral">
                        {en ? "Reason: " : "理由："}{reasonText}
                      </Badge>
                      <Badge tone={liveTrainingPlan?.confidence != null ? "good" : "warning"}>
                        {liveTrainingPlan?.confidence != null
                          ? `${en ? "Personalised: " : "個人化程度："}${(liveTrainingPlan.confidence * 100).toFixed(0)}%`
                          : en
                            ? "Conservative — not enough of your data yet"
                            : "保守建議 — 你的資料還不足以個人化"}
                      </Badge>
                    </div>
                  </div>

                  {/* Sleek Plan Candidate Deck */}
                  <div className="plan-candidate-deck">
                    {(liveTrainingPlan?.candidates ?? [
                      {
                        candidate_id: "c1",
                        workout_type: "REST_DAY",
                        duration_minutes: 0,
                        distance_km: 0,
                        score: 1.0,
                        rationale: [en ? "Recent load is elevated, favor lighter work" : "近期負荷偏高，偏好較輕的訓練"],
                      },
                      {
                        candidate_id: "c2",
                        workout_type: "RECOVERY_RUN",
                        duration_minutes: 20,
                        distance_km: 3.0,
                        score: 0.5,
                        rationale: [en ? "Recent load is elevated, favor lighter work; self-care triage, reduce intensity weight" : "近期負荷偏高，偏好較輕的訓練；適度照護修復，降低強度權重"],
                      },
                    ]).map((cand, i) => {
                      const isSelected = activePlanCandidate
                        ? (activePlanCandidate.candidate_id === cand.candidate_id || activePlanCandidate.workout_type === cand.workout_type)
                        : i === 0;

                      return (
                        <div
                          key={cand.candidate_id || i}
                          className={`plan-candidate-card ${isSelected ? "is-active" : ""}`}
                          onClick={() => setSelectedCandidateId(cand.candidate_id)}
                        >
                          <div className="row" style={{ gap: 12, alignItems: "center", flex: 1, minWidth: 0 }}>
                            <div style={{ flex: "none" }}>
                              {isSelected ? (
                                <Badge tone="accent" dot>
                                  {i === 0 ? (en ? "Top Pick (Active)" : "首選 · 已套用") : (en ? "Active" : "已套用")}
                                </Badge>
                              ) : (
                                <Badge tone={i === 0 ? "good" : "neutral"} dot={i === 0}>
                                  {i === 0 ? (en ? "Top Pick" : "首選推薦") : (en ? "Alternative" : "備選課表")}
                                </Badge>
                              )}
                            </div>
                            <div style={{ minWidth: 0 }}>
                              <div className="row" style={{ gap: 8, alignItems: "center" }}>
                                <strong style={{ fontSize: 13.5, color: isSelected ? "var(--text)" : "var(--text-2)" }}>
                                  {cand.workout_type === "REST_DAY"
                                    ? (en ? "Rest Day" : "休息日")
                                    : cand.workout_type === "RECOVERY_RUN"
                                    ? (en ? "Recovery Run" : "恢復跑")
                                    : cand.workout_type === "EASY_RUN"
                                    ? (en ? "Easy Run" : "輕鬆跑")
                                    : (en ? "Steady Run" : "節奏/穩定跑")}
                                </strong>
                                {cand.duration_minutes > 0 && (
                                  <span className="field-hint" style={{ fontSize: 11.5 }}>
                                    {cand.duration_minutes} min · {cand.distance_km} km
                                  </span>
                                )}
                              </div>
                              <div className="field-hint" style={{ fontSize: 11, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {cand.rationale?.map(r => r.replace("SELF_CARE_LIMIT_INTENSITY", "自我照護模式").replace("自我照護分流", "適度照護修復")).join("；") || (en ? "Recent load elevated, favor lighter training" : "近期負荷偏高，偏好較輕的訓練")}
                              </div>
                            </div>
                          </div>

                          <div style={{ textAlign: "right", flex: "none" }}>
                            <div className="tnum" style={{ fontSize: 14, fontWeight: 750, color: isSelected ? "var(--accent)" : "var(--text)" }}>
                              {cand.score === null ? "—" : cand.score.toFixed(2)}
                              <span style={{ fontSize: 10.5, fontWeight: 500, color: "var(--text-muted)", marginLeft: 2 }}>分</span>
                            </div>
                            <span style={{ fontSize: 10.5, color: isSelected ? "var(--accent-ink)" : "var(--text-muted)" }}>
                              {isSelected ? (en ? "Active selection" : "已套用") : (en ? "Click to apply" : "點擊套用")}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 6, fontSize: 11.5, color: "var(--text-2)", paddingTop: 8, borderTop: "1px solid var(--border)" }}>
                    <div>
                      <span style={{ color: "var(--text-muted)" }}>{en ? "ACWR: " : "負荷比: "}</span>
                      <strong className="tnum" style={{ color: "var(--text)" }}>{trainingLoad.units[0]?.loadRatio != null ? Number(trainingLoad.units[0].loadRatio).toFixed(2) : "—"}</strong>
                    </div>
                    <div>
                      <span style={{ color: "var(--text-muted)" }}>{en ? "Obs Days: " : "觀測天數: "}</span>
                      <strong className="tnum" style={{ color: "var(--text)" }}>{liveTrainingPlan?.inputs?.observation_days ?? "—"}</strong>
                    </div>
                    <div>
                      <span style={{ color: "var(--text-muted)" }}>{en ? "Temp: " : "氣溫: "}</span>
                      <strong className="tnum" style={{ color: "var(--text)" }}>
                        {displayWeather.temperatureC !== null && displayWeather.temperatureC !== undefined ? `${displayWeather.temperatureC.toFixed(1)}°C` : "29.5°C"}
                      </strong>
                    </div>
                    <div>
                      <span style={{ color: "var(--text-muted)" }}>{en ? "Status: " : "狀態評估: "}</span>
                      <strong style={{ color: "var(--text)" }}>{en ? "Rest & Active Recovery" : "建議充分休息與恢復"}</strong>
                    </div>
                  </div>
                </div>
              );
            })()}
          </>
        )}

        {/* Quick Action Footer on Hero */}
        <div className="row-between" style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)", flexWrap: "wrap", gap: 10 }}>
          <div className="row" style={{ gap: 10, alignItems: "center" }}>
            {todayHasRecord ? (
              <Badge tone="good" dot>
                {c.recorded}
              </Badge>
            ) : (
              <Badge tone="neutral">{c.missing}</Badge>
            )}
            {pendingCount > 0 && !online && (
              <Badge tone="warning">
                {interpolate(c.pending, { count: pendingCount })}
              </Badge>
            )}
          </div>
        </div>
      </div>

      {/* 4-Metric Training Load Strip */}
      <div className="grid-4 dashboard-metrics" style={{ marginBottom: 24 }}>
        <Card>
          <StatTile
            label={
              <span className="row" style={{ gap: 4 }}>
                {c.acute}
                <InfoTip text={c.acuteFoot} />
              </span>
            }
            value={primaryUnit ? formatNumber(primaryUnit.acuteLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
          />
        </Card>
        <Card>
          <StatTile
            label={
              <span className="row" style={{ gap: 4 }}>
                {c.chronic}
                <InfoTip text={c.chronicFoot} />
              </span>
            }
            value={primaryUnit ? formatNumber(primaryUnit.chronicLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
          />
        </Card>
        <Card>
          <StatTile
            label={
              <span className="row" style={{ gap: 4 }}>
                {c.ratio}
                {primaryUnit?.loadRatio !== null && <InfoTip text={c.ratioFoot} />}
              </span>
            }
            value={
              primaryUnit?.loadRatio === null || primaryUnit === null
                ? c.noCalc
                : primaryUnit.loadRatio.toFixed(2)
            }
            foot={primaryUnit?.loadRatio === null ? c.ratioLow : undefined}
          />
        </Card>
        <Card>
          <StatTile
            label={c.observations}
            value={`${trainingLoad.observationDays}`}
            unit={c.days28}
            foot={
              <span className="row" style={{ gap: 6 }}>
                <DataQualityBadge quality={trainingLoad.dataQuality} />
              </span>
            }
          />
        </Card>
      </div>

      {/* Dual Column Layout: Chart & Stream */}
      <div className="dashboard-split">
        {/* Left Column: Coach assignments, then 28-day Chart */}
        <div className="stack">
          {/* Coach-assigned workouts (if any) -- shown above the chart so it
              isn't mistaken for "not synced" just because it's out of view. */}
          {upcomingAssignedWorkouts.length > 0 && (
            <Card title={c.assigned} subtitle={c.assignedSub}>
              <div className="stack-sm">
                {upcomingAssignedWorkouts.map((w) => (
                  <AssignedWorkoutRow key={w.id} workout={w} locale={locale} statusLabel={assignedStatusLabel[w.status]} />
                ))}
              </div>
            </Card>
          )}

          <Card
            title={c.chart}
            subtitle={interpolate(c.chartSub, { unit: primaryUnit ? primaryUnit.unit : "AU" })}
            actions={
              <Link className="btn btn-secondary btn-sm" to="/app/load">
                {c.trend}
              </Link>
            }
          >
            <div className="chart-toolbar">
              <DateRangePicker
                range={loadRange}
                maxDate={today}
                defaultRange={defaultChartRange}
                onChange={(next) => setLoadRange(clampChartRange(next, today))}
              />
            </div>
            <DailyLoadChart
              points={loadChartPoints}
              unitLabel={primaryUnit?.unit ?? "AU"}
              height={230}
            />
          </Card>

          <Card title={c.runChart} subtitle={c.runChartSub}>
            <div className="chart-toolbar">
              <DateRangePicker
                range={runRange}
                maxDate={today}
                defaultRange={defaultChartRange}
                onChange={(next) => setRunRange(clampChartRange(next, today))}
              />
            </div>
            <DailyDistancePaceChart points={runChartPoints} height={230} />
          </Card>
        </div>

        {/* Right Column: Weather, Body Status, Recent Activities */}
        <div className="stack">
          {/* Weather & Pace Adjustment */}
          <Card
            title={c.weather}
            subtitle={interpolate(c.weatherCity, { city: displayWeather.city })}
            actions={<WeatherStateBadge state={displayWeather.state} />}
          >
            {apiConfigured && weatherStatus === "loading" && !liveWeather ? (
              <Notice tone="neutral" icon="info">
                {c.weatherLoading}
              </Notice>
            ) : displayWeather.state === "UNAVAILABLE" ? (
              <Notice tone="neutral" icon="cloud">
                {c.weatherUnavailable}
              </Notice>
            ) : (
              <div className="stack-sm">
                <div className="grid-2">
                  <StatTile
                    small
                    label={c.temperature}
                    value={
                      displayWeather.climateNormalReferenceC !== null && displayWeather.temperatureC !== null ? (
                        <InfoTip
                          text={interpolate(c.vsNormal, {
                            normal: displayWeather.climateNormalReferenceC.toFixed(1),
                            sign: displayWeather.temperatureC >= displayWeather.climateNormalReferenceC ? "+" : "",
                            diff: (displayWeather.temperatureC - displayWeather.climateNormalReferenceC).toFixed(1),
                          })}
                        >
                          <span>{displayWeather.temperatureC.toFixed(1)}</span>
                        </InfoTip>
                      ) : (
                        (displayWeather.temperatureC?.toFixed(1) ?? "—")
                      )
                    }
                    unit="°C"
                  />
                  <StatTile small label={c.humidity} value={`${displayWeather.humidityPct ?? "—"}`} unit="%" />
                </div>
                <div className="row-between" style={{ padding: "10px 12px", background: "var(--surface-2)", borderRadius: "var(--r-sm)" }}>
                  <span className="muted" style={{ fontSize: 12.5 }}>{c.paceAdjust}</span>
                  <strong className="tnum" style={{ color: "var(--accent)" }}>
                    {formatSpeedLossLabel(speedLossPct, c)}
                  </strong>
                </div>
                {/* Hidden per user request -- the absolute El Helou curve reads
                    as a large %% on essentially any day in a warm city (see
                    speedLossPctRelativeToNormal's docstring), so it read as
                    confusing small print next to the headline relative figure
                    above. Kept in code, not rendered.
                {displayWeather.speedLossPctUnadjusted !== null && (
                  <span className="field-hint" style={{ fontSize: 10.5 }}>
                    {interpolate(c.absoluteCurveNote, { pct: displayWeather.speedLossPctUnadjusted.toFixed(1) })}
                  </span>
                )}
                */}
                {(adjustedTargetPace !== null || weatherAdjustedPaceRange !== null) && (
                  <div style={{ padding: "10px 12px", background: "var(--accent-soft)", borderRadius: "var(--r-sm)" }}>
                    <div className="row-between" style={{ alignItems: "baseline" }}>
                      <span className="row" style={{ gap: 4, alignItems: "center" }}>
                        <span className="muted" style={{ fontSize: 12.5 }}>{c.adjustedPace}</span>
                        <InfoTip text={c.adjustedPaceHint} />
                      </span>
                      <strong className="tnum" style={{ color: "var(--accent-ink)", whiteSpace: "nowrap" }}>
                        {adjustedTargetPace !== null
                          ? formatPace(adjustedTargetPace)
                          : `${formatPace(weatherAdjustedPaceRange![0])}–${formatPace(weatherAdjustedPaceRange![1])}`}
                      </strong>
                    </div>
                  </div>
                )}

                {displayWeather.timeOfDayEstimates.length > 0 && (
                  <div>
                    <div className="field-label" style={{ marginBottom: 6 }}>{c.timeOfDay}</div>
                    <div className="grid-3" style={{ gap: 6 }}>
                      {displayWeather.timeOfDayEstimates.map((slot) => {
                        const slotLabel = slot.label === "morning" ? c.morning : slot.label === "midday" ? c.midday : c.evening;
                        const slotPace = paceForPct(slot.speedLossPct);
                        return (
                          <div
                            key={slot.label}
                            style={{ padding: "8px 10px", background: "var(--surface-2)", borderRadius: "var(--r-sm)", textAlign: "center" }}
                          >
                            <div className="field-hint" style={{ fontSize: 10.5 }}>{slotLabel}</div>
                            <div className="tnum" style={{ fontSize: 15, fontWeight: 700, margin: "3px 0" }}>
                              {slot.temperatureC.toFixed(0)}°C
                            </div>
                            {(slotPace.single !== null || slotPace.range !== null) && (
                              <div className="tnum" style={{ fontSize: 11, color: "var(--accent-ink)", whiteSpace: "nowrap" }}>
                                {slotPace.single !== null
                                  ? formatPace(slotPace.single)
                                  : `${formatPace(slotPace.range![0])}–${formatPace(slotPace.range![1])}`}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    {/* Hidden per user request, kept in code, not rendered.
                    <div className="field-hint" style={{ fontSize: 10.5, marginTop: 6 }}>{c.timeOfDayHint}</div>
                    */}
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* Explore a different day's conditions -- same evaluation as today */}
          <ConditionsExplorer
            actualTemperatureC={displayWeather.temperatureC}
            actualHumidityPct={displayWeather.humidityPct}
          />

          {/* Body Status Summary */}
          <Card
            title={c.body}
            actions={
              <Link className="btn btn-secondary btn-sm" to="/app/body">
                {c.report}
              </Link>
            }
          >
            {latestInjury ? (
              <div className="stack-sm">
                <div className="row-between">
                  <span className="muted">{c.latest}</span>
                  <SeverityBadge band={latestInjury.severityBand} />
                </div>
                <div className="row-between">
                  <span className="muted">{c.bodyPart}</span>
                  <strong>{latestInjury.bodyPart || "—"}</strong>
                </div>
                <span className="field-hint">
                  {interpolate(c.injuryNote, { date: latestInjury.localDate })}
                </span>
              </div>
            ) : (
              <div className="row" style={{ gap: 8, alignItems: "center" }}>
                <Icon name="check" size={16} />
                <span className="field-hint" style={{ color: "var(--text-2)" }}>{c.noInjury}</span>
              </div>
            )}
          </Card>

          {/* Recent Completed Activities */}
          <Card
            title={c.recent}
            actions={
              <Link className="btn btn-ghost btn-sm" to="/app/history">
                {c.all}
              </Link>
            }
            flush
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {recentActivities.map((activity) => (
                <li
                  key={activity.id}
                  style={{
                    padding: "12px 18px",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div className="row-between">
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                        {formatDuration(activity.durationMinutes, locale)}
                        {activity.distanceKm && ` · ${activity.distanceKm} km`}
                        {activity.rpe !== null && ` · RPE ${activity.rpe}`}
                      </div>
                      <div className="field-hint" style={{ fontSize: 11.5 }}>
                        {activity.localTrainingDate} · {c.sessionLoad}{" "}
                        {formatNumber(activity.sessionLoad)} {UNIT_SHORT[activity.unit]}
                      </div>
                    </div>
                    <SyncChip state={activity.syncState} />
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}

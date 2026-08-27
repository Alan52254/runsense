import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, DateRangePicker, EmptyState, Notice, Segmented, StatTile } from "../../components/ui.tsx";
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
    toneOff: "已關閉語氣調配", reviewed: "由 {reviewer} 審核之安全建議庫",
    explainTitle: "建議產生方式", explainBody: "系統依據選手之 7/28 天負荷比與資料完整度計算訓練處方，並自審核通過之文案庫選取合適提醒。敏感個資與 GPS 位置絕不傳遞予文字模型。",
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
    recent: "近期訓練活動", all: "查看全部紀錄", easyRun: "輕鬆有氧跑", systemDefault: "系統預設",
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
    toneOff: "Motivational tone off", reviewed: "Reviewed by {reviewer}",
    explainTitle: "How this is calculated", explainBody: "Prescriptions are determined deterministically from load ratios. Names and GPS are never shared with text models.",
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
    recent: "Recent Activities", all: "View All History", easyRun: "Easy Aerobic Run", systemDefault: "System Default",
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
            {workout.localDate} · {workout.durationMinutes} {locale === "zh-TW" ? "分" : "min"} · {workout.intensityLabel}
            {estimate.totalMeters > 0 && ` · ${formatEstimatedKmLabel(estimate)}`}
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {structure.length > 0 && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExpanded((v) => !v)}>
              {expanded ? (locale === "en" ? "Hide" : "收合") : (locale === "en" ? "Workout details" : "課表內容")}
            </button>
          )}
          <Badge tone={workout.status === "MISSED" ? "warning" : "neutral"}>{statusLabel}</Badge>
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
          timeOfDayEstimates: liveWeather.time_of_day_estimates.map((estimate) => ({
            label: estimate.label,
            hour: estimate.hour,
            temperatureC: estimate.temperature_c,
            speedLossPct: estimate.speed_loss_pct,
          })),
        }
      : weather;

  const displayRecommendation =
    apiConfigured && liveGuidance
      ? {
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
        }
      : recommendation;

  const displayTone =
    apiConfigured && liveGuidance
      ? { id: liveGuidance.tone_variant_id, text: liveGuidance.tone_text, reviewedBy: liveGuidance.tone_reviewed_by }
      : shownTone;

  const displayedWorkoutType =
    locale === "en" && displayRecommendation.workoutType === "輕鬆有氧跑"
      ? c.easyRun
      : displayRecommendation.workoutType;

  const displayedToneText =
    locale === "en" && displayTone.text === "以下是今天的課表。" ? c.defaultTone : displayTone.text;
  const displayedReviewer =
    locale === "en" && displayTone.reviewedBy === "系統預設" ? c.systemDefault : displayTone.reviewedBy;

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
        <div className="row-between" style={{ marginBottom: 16 }}>
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
            {/* Explicit athlete choice, not "whichever exists wins" -- a
                coach assignment silently overriding the system suggestion
                (or vice versa) left the athlete unsure which plan they were
                actually supposed to follow today. */}
            <Segmented
              value={preferences.trainingSource}
              onChange={(next) => setPreference("trainingSource", next)}
              options={[
                { value: "system" as const, label: c.systemSuggested },
                { value: "coach" as const, label: c.coachArranged },
              ]}
            />
          </div>
          {displayWeather.temperatureC !== null && (
            <div className="row" style={{ gap: 6, alignItems: "center", fontSize: 13, color: "var(--text-2)" }}>
              <Icon name="cloud" size={16} />
              <span>{displayWeather.city}: {displayWeather.temperatureC?.toFixed(0)}°C · {displayWeather.humidityPct}% 濕度</span>
            </div>
          )}
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

            {/* Coach Insight Strip -- only meaningful for the algorithmic
                plan; a coach's own assignment needs no synthesized commentary. */}
            <div className="coach-insight-box">
              <div className="row-between" style={{ alignItems: "flex-start", gap: 12 }}>
                <div className="row" style={{ gap: 10 }}>
                  <span className="coach-avatar-bubble">
                    <Icon name="coach-note" size={16} />
                  </span>
                  <div>
                    <div className="row" style={{ gap: 8, alignItems: "center", marginBottom: 2 }}>
                      <strong style={{ fontSize: 13 }}>{c.reminder}</strong>
                      <span className="field-hint" style={{ fontSize: 11 }}>
                        {interpolate(c.reviewed, { reviewer: displayedReviewer })}
                      </span>
                    </div>
                    <p style={{ fontSize: 13.5, color: "var(--text)", margin: 0, lineHeight: 1.5 }}>
                      {displayedToneText}
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
          </>
        )}

        {/* Quick Action Footer on Hero */}
        <div className="row-between" style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border)", flexWrap: "wrap", gap: 10 }}>
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

          <div className="row" style={{ gap: 10 }}>
            <Link className="btn btn-primary" to="/app/run">
              <Icon name="runner" size={16} />
              {c.liveRun}
            </Link>
          </div>
        </div>
      </div>

      {/* 4-Metric Training Load Strip */}
      <div className="grid-4 dashboard-metrics" style={{ marginBottom: 24 }}>
        <Card>
          <StatTile
            label={c.acute}
            value={primaryUnit ? formatNumber(primaryUnit.acuteLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
            foot={c.acuteFoot}
          />
        </Card>
        <Card>
          <StatTile
            label={c.chronic}
            value={primaryUnit ? formatNumber(primaryUnit.chronicLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
            foot={c.chronicFoot}
          />
        </Card>
        <Card>
          <StatTile
            label={c.ratio}
            value={
              primaryUnit?.loadRatio === null || primaryUnit === null
                ? c.noCalc
                : primaryUnit.loadRatio.toFixed(2)
            }
            foot={
              primaryUnit?.loadRatio === null
                ? c.ratioLow
                : c.ratioFoot
            }
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
                        <span className="info-tip" tabIndex={0}>
                          <span>{displayWeather.temperatureC.toFixed(1)}</span>
                          <span className="info-tip-bubble">
                            {interpolate(c.vsNormal, {
                              normal: displayWeather.climateNormalReferenceC.toFixed(1),
                              sign: displayWeather.temperatureC >= displayWeather.climateNormalReferenceC ? "+" : "",
                              diff: (displayWeather.temperatureC - displayWeather.climateNormalReferenceC).toFixed(1),
                            })}
                          </span>
                        </span>
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
                        <span className="info-tip" tabIndex={0}>
                          <span className="info-tip-icon">
                            <Icon name="info" size={13} />
                          </span>
                          <span className="info-tip-bubble">{c.adjustedPaceHint}</span>
                        </span>
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

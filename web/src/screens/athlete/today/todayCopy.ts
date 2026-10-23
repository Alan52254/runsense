/* Copy for the 今日訓練 screen and its panels. */

import { formatPace, formatPaceRange } from "../../../lib/format.ts";
import { climateMomentLabel, paceShiftText, type ClimateSlot } from "../../../lib/climateShift.ts";

export const DASHBOARD_COPY = {
  "zh-TW": {
    timezone: "時區：{timezone}", log: "記錄訓練", liveRun: "開始跑步監控",
    acute: "近 7 天負荷", acuteFoot: "7 天累積訓練量", chronic: "28 天基準負荷",
    chronicFoot: "換算每週基準負荷", ratio: "ACWR 負荷比", noCalc: "計算中",
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
    explainTitle: "建議產生方式", explainBody: "系統會依你的 ACWR 負荷比與資料完整度，自動選出合適的提醒文字。你的個資與 GPS 位置絕不會被傳送給外部的文字生成服務。",
    chart: "每日負荷趨勢", chartSub: "單位 {unit}", trend: "深度分析",
    runChart: "每日跑量與配速", runChartSub: "距離（長條）與平均配速（折線）",
    todo: "今日動態與狀態", recorded: "今日已完成訓練紀錄！",
    missing: "今日尚未有訓練紀錄，可即時開始跑步或手動紀錄。",
    pending: "有 {count} 筆紀錄待同步至伺服器", queue: "查看佇列",
    weather: "天候狀況與配速補償", weatherCity: "地點：{city}", weatherLoading: "正在取得天氣資料…",
    weatherUnavailable: "目前無法取得即時天氣資料", temperature: "氣溫", humidity: "相對濕度",
    paceAdjust: "氣候配速影響", climateShift: "{moment} 配速{shift}", observed: "觀測時間 {time}",
    adjustedPace: "現在的等效配速", adjustedPaceHint: "依今日建議配速換算",
    vsNormal: "比傍晚常態溫度（{normal}°C）{sign}{diff}°C",
    absoluteCurveNote: "（未考慮季節與時段：對比論文絕對最佳溫度為 +{pct}%）",
    timeOfDay: "早中晚溫度預估", timeOfDayHint: "依氣候常態＋日出日落換算，不是即時預報",
    morning: "早上 6:00", midday: "中午 12:00", evening: "晚上 18:30",
    body: "身體與疲勞狀況", report: "快速回報", latest: "最新狀態", bodyPart: "主要部位",
    injuryNote: "{date} 回報", noInjury: "尚無身體回報，無法判斷目前狀況。",
    recent: "近期訓練活動", all: "查看全部紀錄", easyRun: "輕鬆有氧跑",
    rulePace: "系統規則配速", paceAwaiting: "配速待系統或教練提供",
    rulePaceHint: "輕鬆跑紀錄還不足以推算你的個人配速，此為系統依課表類型的規則配速",
    sessionLoad: "負荷",
    assigned: "教練指派課表", assignedSub: "教練團預先規劃之訓練排程",
    assignedNone: "目前沒有即將到來的指派課表", assignedScheduled: "預計執行", assignedCompleted: "已完成",
    assignedMissed: "未執行",
    weatherAdjustedPace: "天候等效配速",
    coachArranged: "教練安排", systemSuggested: "系統建議", intensity: "強度",
    coachPaceWeatherNote: "配速已依現在氣溫（相對傍晚常態溫度）調整：{shift}，教練原訂配速已假設是傍晚常態氣溫",
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
    paceAdjust: "Weather Pace Impact", climateShift: "Pace {moment}: {shift}", observed: "Observed {time}",
    adjustedPace: "Adjusted pace (now)", adjustedPaceHint: "Converted from today's suggested pace",
    vsNormal: "{sign}{diff}°C vs. typical early-evening temperature ({normal}°C)",
    absoluteCurveNote: "(ignoring season/time of day: +{pct}% vs. the paper's absolute optimum)",
    timeOfDay: "Estimated temperature by time of day", timeOfDayHint: "From climate normals + today's sunrise/sunset, not a live forecast",
    morning: "6:00 AM", midday: "12:00 PM", evening: "6:30 PM",
    body: "Body Status & Discomfort", report: "Report", latest: "Latest status", bodyPart: "Body Part",
    injuryNote: "Reported on {date}", noInjury: "No body report yet; current condition is unknown.",
    recent: "Recent Activities", all: "View All History", easyRun: "Easy Aerobic Run",
    rulePace: "System rule pace", paceAwaiting: "Pace pending from system or coach",
    rulePaceHint: "Too few easy runs to work out your own pace yet; this is the system rule for the workout type",
    sessionLoad: "load",
    assigned: "Coach Assignments", assignedSub: "Scheduled by your coaching staff",
    assignedNone: "No scheduled assignments", assignedScheduled: "Scheduled", assignedCompleted: "Completed",
    assignedMissed: "Missed",
    weatherAdjustedPace: "Weather Adjusted Pace",
    coachArranged: "Coach-arranged", systemSuggested: "System-suggested", intensity: "Intensity",
    coachPaceWeatherNote: "Pace adjusted for the current temperature vs. typical early-evening heat ({shift}) -- your coach's target is assumed calibrated for a typical evening run",
    segmentWeatherLoading: "Calculating weather impact…",
    segmentEstimatedTime: "Est. start {time}",
    segmentPaceAdjusted: "This block: {from} → {to}",
    segmentPaceUnchanged: "Typical for this time -- no adjustment needed",
  },
} as const;

export type TodayCopy = Record<keyof (typeof DASHBOARD_COPY)["zh-TW"], string>;

export function interpolate(template: string, params: Record<string, string | number>): string {
  return Object.entries(params).reduce((value, [key, replacement]) => value.replaceAll(`{${key}}`, String(replacement)), template);
}

/** "現在 配速快 0.8%" / "18:30 時段 配速慢 0.3%": a climate shift with the
 *  moment it describes, worded by lib/climateShift.ts so every surface uses
 *  one sign convention (slower is 慢, faster is 快). `slot` null is now. */
export function climateShiftLabel(pct: number, slot: ClimateSlot | null, c: TodayCopy, locale: "zh-TW" | "en"): string {
  return interpolate(c.climateShift, { moment: climateMomentLabel(slot, locale), shift: paceShiftText(pct, locale) });
}

/** A pace in whichever shape the plan offers, as text; null when neither. */
export function paceShapeText(p: { single: number | null; range: [number, number] | null }): string | null {
  if (p.single !== null) return formatPace(p.single);
  if (p.range !== null) return formatPaceRange(p.range[0], p.range[1]);
  return null;
}

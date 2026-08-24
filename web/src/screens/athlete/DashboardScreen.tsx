import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Notice, StatTile } from "../../components/ui.tsx";
import { DailyLoadChart } from "../../components/charts.tsx";
import {
  DataQualityBadge,
  SeverityBadge,
  SyncChip,
  WeatherStateBadge,
} from "../../components/domain.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { apiConfigured } from "../../data/apiClient.ts";
import { useLocale } from "../../state/LocaleContext.tsx";
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
    loadingPlan: "正在載入今日課表…", planError: "無法載入今日課表，請稍後再試。",
    duration: "預計時長", distance: "預計距離", pace: "目標配速", reminder: "教練洞見",
    toneOff: "已關閉語氣調配", reviewed: "由 {reviewer} 審核之安全建議庫",
    explainTitle: "建議產生方式", explainBody: "系統依據選手之 7/28 天負荷比與資料完整度計算訓練處方，並自審核通過之文案庫選取合適提醒。敏感個資與 GPS 位置絕不傳遞予文字模型。",
    chart: "近 28 天每日負荷趨勢", chartSub: "單位 {unit}", trend: "深度分析",
    todo: "今日動態與狀態", recorded: "今日已完成訓練紀錄！", restMarked: "今日已設定為休息日，計入觀測天數。",
    undo: "復原", missing: "今日尚未有訓練紀錄，可即時開始跑步或手動紀錄。",
    rest: "標記為休息日", pending: "有 {count} 筆紀錄待同步至伺服器", queue: "查看佇列",
    weather: "天候狀況與配速補償", weatherCity: "地點：{city}", weatherLoading: "正在取得天氣資料…",
    weatherUnavailable: "目前無法取得即時天氣資料", temperature: "氣溫", humidity: "相對濕度",
    paceAdjust: "氣候配速補償", secondsKm: "+{seconds} 秒 / km", observed: "觀測時間 {time}",
    body: "身體與疲勞狀況", report: "快速回報", latest: "最新狀態", bodyPart: "主要部位",
    injuryNote: "{date} 回報", noInjury: "身體狀態良好，無不適紀錄。",
    recent: "近期訓練活動", all: "查看全部紀錄", easyRun: "輕鬆有氧跑", systemDefault: "系統預設",
    cityUnset: "未設定城市", defaultTone: "請依循今日課表配速，注意步頻與呼吸節奏。", sessionLoad: "負荷",
    assigned: "教練指派課表", assignedSub: "教練團預先規劃之訓練排程",
    assignedNone: "目前沒有即將到來的指派課表", assignedScheduled: "預計執行", assignedCompleted: "已完成",
    assignedMissed: "未執行",
    weatherAdjustedPace: "天候等效配速",
  },
  en: {
    timezone: "Timezone: {timezone}", log: "Log Workout", liveRun: "Start Live Run",
    acute: "7-Day Load", acuteFoot: "Acute 7-day cumulative load", chronic: "28-Day Baseline",
    chronicFoot: "Weekly chronic baseline", ratio: "Acute / Chronic Ratio", noCalc: "Calculating",
    ratioLow: "Hidden due to insufficient observations", ratioFoot: "7-day load ÷ 28-day baseline", observations: "Observation Days",
    days28: "/ 28 days", plan: "Today's Workout", planSub: "Dynamic prescription from load trend",
    rationale: "Basis: training load trend & recovery", collapse: "Collapse", explain: "Methodology",
    loadingPlan: "Loading today's prescription…", planError: "Unable to load today's prescription.",
    duration: "Target Duration", distance: "Target Distance", pace: "Target Pace", reminder: "Coach Insight",
    toneOff: "Motivational tone off", reviewed: "Reviewed by {reviewer}",
    explainTitle: "How this is calculated", explainBody: "Prescriptions are determined deterministically from load ratios. Names and GPS are never shared with text models.",
    chart: "28-Day Daily Load Trend", chartSub: "Unit: {unit}", trend: "Deep Dive",
    todo: "Today's Status", recorded: "Workout recorded for today!", restMarked: "Marked as rest day. Counts toward observation days.",
    undo: "Undo", missing: "No workout logged today yet. Ready to start running?",
    rest: "Mark as Rest Day", pending: "{count} records pending sync", queue: "View Queue",
    weather: "Weather & Pace Adaptation", weatherCity: "City: {city}", weatherLoading: "Loading weather…",
    weatherUnavailable: "Live weather data unavailable", temperature: "Temperature", humidity: "Humidity",
    paceAdjust: "Weather Pace Offset", secondsKm: "+{seconds} s / km", observed: "Observed {time}",
    body: "Body Status & Discomfort", report: "Report", latest: "Latest status", bodyPart: "Body Part",
    injuryNote: "Reported on {date}", noInjury: "Feeling great, no discomfort reported.",
    recent: "Recent Activities", all: "View All History", easyRun: "Easy Aerobic Run", systemDefault: "System Default",
    cityUnset: "City not set", defaultTone: "Follow today's target pace and maintain smooth breathing.", sessionLoad: "load",
    assigned: "Coach Assignments", assignedSub: "Scheduled by your coaching staff",
    assignedNone: "No scheduled assignments", assignedScheduled: "Scheduled", assignedCompleted: "Completed",
    assignedMissed: "Missed",
    weatherAdjustedPace: "Weather Adjusted Pace",
  },
} as const;

function interpolate(template: string, params: Record<string, string | number>): string {
  return Object.entries(params).reduce((value, [key, replacement]) => value.replaceAll(`{${key}}`, String(replacement)), template);
}

export function DashboardScreen() {
  const { auth } = useAuth();
  const { locale } = useLocale();
  const c = DASHBOARD_COPY[locale];
  const {
    today,
    trainingLoad,
    allActivities,
    restDays,
    injuryReports,
    weather,
    recommendation,
    toneVariants,
    selectedToneVariantId,
    preferences,
    pendingCount,
    confirmRestDay,
    confirmedRestDatesThisSession,
    liveWeather,
    weatherStatus,
    liveGuidance,
    myAssignedWorkouts,
    online,
  } = useWorkspace();

  const [showLlmContract, setShowLlmContract] = useState(false);

  const primaryUnit = trainingLoad.units[0] ?? null;
  const todayHasRecord = allActivities.some((a) => a.localTrainingDate === today);
  const todayIsRest = apiConfigured
    ? confirmedRestDatesThisSession.has(today)
    : restDays.some((r) => r.localDate === today);
  const latestInjury = injuryReports[0];

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
          paceAdjustmentSecPerKm: liveWeather.pace_adjustment_sec_per_km,
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

  // Weather adjusted target pace
  const paceAdjustment = displayWeather.paceAdjustmentSecPerKm ?? 0;
  const adjustedTargetPace = displayRecommendation.targetPaceSecPerKm
    ? displayRecommendation.targetPaceSecPerKm + paceAdjustment
    : null;

  const recentActivities = allActivities.slice(0, 4);
  const upcomingAssignedWorkouts = myAssignedWorkouts
    .filter((w) => w.localDate >= today)
    .sort((a, b) => a.localDate.localeCompare(b.localDate))
    .slice(0, 3);

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

      {/* Hero Workout of the Day Card */}
      <div className="card hero-workout-card" style={{ marginBottom: 24, padding: 24 }}>
        <div className="row-between" style={{ marginBottom: 16 }}>
          <div className="row" style={{ gap: 10, alignItems: "center" }}>
            <span className="hero-workout-badge">
              <Icon name="activity" size={16} />
              {c.plan}
            </span>
            <span style={{ fontSize: 18, fontWeight: 700 }}>{displayedWorkoutType}</span>
          </div>
          {displayWeather.temperatureC !== null && (
            <div className="row" style={{ gap: 6, alignItems: "center", fontSize: 13, color: "var(--text-2)" }}>
              <Icon name="cloud" size={16} />
              <span>{displayWeather.city}: {displayWeather.temperatureC?.toFixed(0)}°C · {displayWeather.humidityPct}% 濕度</span>
            </div>
          )}
        </div>

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

        {/* Quick Action Footer on Hero */}
        <div className="row-between" style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border)", flexWrap: "wrap", gap: 10 }}>
          <div className="row" style={{ gap: 10, alignItems: "center" }}>
            {todayHasRecord ? (
              <Badge tone="good" dot>
                {c.recorded}
              </Badge>
            ) : todayIsRest ? (
              <div className="row" style={{ gap: 8, alignItems: "center" }}>
                <Badge tone="accent">{c.restMarked}</Badge>
                <Button size="sm" variant="ghost" onClick={() => void confirmRestDay(today, false)}>
                  {c.undo}
                </Button>
              </div>
            ) : (
              <Button size="sm" variant="secondary" icon="check" onClick={() => void confirmRestDay(today)}>
                {c.rest}
              </Button>
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
        {/* Left Column: 28-day Chart */}
        <div className="stack">
          <Card
            title={c.chart}
            subtitle={interpolate(c.chartSub, { unit: primaryUnit ? primaryUnit.unit : "AU" })}
            actions={
              <Link className="btn btn-secondary btn-sm" to="/app/load">
                {c.trend}
              </Link>
            }
          >
            <DailyLoadChart
              points={trainingLoad.daily}
              unitLabel={primaryUnit?.unit ?? "AU"}
              height={230}
            />
          </Card>

          {/* Coach-assigned workouts (if any) */}
          {upcomingAssignedWorkouts.length > 0 && (
            <Card title={c.assigned} subtitle={c.assignedSub}>
              <div className="stack-sm">
                {upcomingAssignedWorkouts.map((w) => (
                  <div className="row-between" key={w.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                    <div>
                      <div style={{ fontSize: 13.5, fontWeight: 600 }}>{w.title}</div>
                      <div className="field-hint">
                        {w.localDate} · {w.durationMinutes} {locale === "zh-TW" ? "分" : "min"} · {w.intensityLabel}
                      </div>
                    </div>
                    <Badge tone={w.status === "MISSED" ? "warning" : "neutral"}>
                      {assignedStatusLabel[w.status]}
                    </Badge>
                  </div>
                ))}
              </div>
            </Card>
          )}
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
                    value={displayWeather.temperatureC?.toFixed(1) ?? "—"}
                    unit="°C"
                  />
                  <StatTile small label={c.humidity} value={`${displayWeather.humidityPct ?? "—"}`} unit="%" />
                </div>
                <div className="row-between" style={{ padding: "10px 12px", background: "var(--surface-2)", borderRadius: "var(--r-sm)" }}>
                  <span className="muted" style={{ fontSize: 12.5 }}>{c.paceAdjust}</span>
                  <strong className="tnum" style={{ color: "var(--accent)" }}>
                    {interpolate(c.secondsKm, { seconds: displayWeather.paceAdjustmentSecPerKm ?? 0 })}
                  </strong>
                </div>
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

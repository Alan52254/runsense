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
import {
  formatDuration,
  formatLocalDateLong,
  formatNumber,
  formatPace,
  formatRelative,
  UNIT_SHORT,
} from "../../lib/format.ts";

export function DashboardScreen() {
  const { auth } = useAuth();
  const {
    today,
    trainingLoad,
    activities,
    restDays,
    injuryReports,
    weather,
    recommendation,
    toneVariants,
    selectedToneVariantId,
    emotionalContext,
    preferences,
    pendingCount,
    confirmRestDay,
  } = useWorkspace();

  const [showLlmContract, setShowLlmContract] = useState(false);

  const primaryUnit = trainingLoad.units[0] ?? null;
  const todayHasRecord = activities.some((a) => a.localTrainingDate === today);
  const todayIsRest = restDays.some((r) => r.localDate === today);
  const latestInjury = injuryReports[0];

  // REQ-AI-006: the runtime LLM output is a tone_variant_id and nothing else.
  // The text below is looked up from the human-reviewed template library.
  const tone = useMemo(
    () => toneVariants.find((t) => t.id === selectedToneVariantId) ?? toneVariants[0],
    [toneVariants, selectedToneVariantId],
  );
  const fallbackTone = toneVariants.find((t) => t.id === "NEUTRAL_FALLBACK")!;
  const shownTone = preferences.llmToneEnabled ? tone : fallbackTone;

  const recentActivities = activities.slice(0, 4);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">
            {auth?.athlete.name}，{formatLocalDateLong(today)}
          </h1>
          <p className="page-desc">
            所有日期以你的時區 {auth?.athlete.timezone} 判定，不是伺服器所在時區。
          </p>
        </div>
        <Link className="btn btn-primary" to="/app/log">
          <Icon name="plus" size={16} />
          記錄訓練
        </Link>
      </div>

      {/* ---- Metric row. REQ-METRIC-001: numbers and a quality label only —
             deliberately no red/amber/green state on the ratio. ---- */}
      <div className="grid-4">
        <Card>
          <StatTile
            label="7 天負荷 acute_load"
            value={primaryUnit ? formatNumber(primaryUnit.acuteLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
            foot="過去 7 天 session_load 總和"
          />
        </Card>
        <Card>
          <StatTile
            label="28 天週等效 chronic_load"
            value={primaryUnit ? formatNumber(primaryUnit.chronicLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
            foot="28 天總和 ÷ 4"
          />
        </Card>
        <Card>
          <StatTile
            label="負荷比值 load_ratio"
            value={
              primaryUnit?.loadRatio === null || primaryUnit === null
                ? "不計算"
                : primaryUnit.loadRatio.toFixed(2)
            }
            foot={
              primaryUnit?.loadRatio === null
                ? "資料不足時不顯示比值"
                : "acute ÷ chronic"
            }
          />
        </Card>
        <Card>
          <StatTile
            label="觀測天數 observation_days"
            value={`${trainingLoad.observationDays}`}
            unit="/ 28 天"
            foot={
              <span className="row" style={{ gap: 6 }}>
                <DataQualityBadge quality={trainingLoad.dataQuality} />
              </span>
            }
          />
        </Card>
      </div>

      <div className="dashboard-split">
        <div className="stack">
          {/* ---- Today's prescription ---- */}
          <Card
            title="今天的課表"
            subtitle="處方欄位由伺服器直接渲染，沒有經過 LLM。"
            reqTags={["REQ-AI-004"]}
            actions={<Badge tone="accent">{recommendation.workoutType}</Badge>}
            footer={
              <div className="row-between">
                <span>
                  演算法版本 <code className="mono">{recommendation.algorithmVersion}</code> ·
                  調整原因碼 <code className="mono">{recommendation.adjustmentReasonCode}</code>
                </span>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowLlmContract((v) => !v)}
                >
                  {showLlmContract ? "收合" : "這段文字怎麼來的？"}
                </button>
              </div>
            }
          >
            <div className="stack">
              <div className="grid-3">
                <StatTile
                  small
                  label="時長"
                  value={formatDuration(recommendation.durationMinutes)}
                />
                <StatTile
                  small
                  label="距離"
                  value={recommendation.distanceKm ? `${recommendation.distanceKm}` : "—"}
                  unit={recommendation.distanceKm ? "km" : undefined}
                />
                <StatTile
                  small
                  label="目標配速"
                  value={formatPace(recommendation.targetPaceSecPerKm)}
                />
              </div>

              <hr className="divider" />

              <div className="stack-sm">
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <Icon name="sparkle" size={15} />
                  <strong style={{ fontSize: 13 }}>教練語氣</strong>
                  <span className="req-tag">tone_variant_id: {shownTone.id}</span>
                  {!preferences.llmToneEnabled && (
                    <Badge tone="neutral">已關閉情緒建議，改用固定模板</Badge>
                  )}
                </div>
                <p style={{ fontSize: 14, lineHeight: 1.75 }}>{shownTone.text}</p>
                <span className="field-hint">
                  文案由 {shownTone.reviewedBy} 於人工審核後納入模板庫，不是即時生成。
                </span>
              </div>

              {showLlmContract && (
                <Notice tone="accent" icon="shield" title="Runtime 的 LLM 權限只有這一件事">
                  <div className="stack-sm" style={{ marginTop: 6 }}>
                    <div className="mono">
                      Deterministic Engine → emotional_context ={" "}
                      {JSON.stringify(emotionalContext)}
                    </div>
                    <div className="mono">
                      LLM → {"{ \"tone_variant_id\": \""}
                      {shownTone.id}
                      {"\" }"}
                    </div>
                    <div className="mono">
                      Server → template_library[{shownTone.id}] → 顯示文字
                    </div>
                    <div>
                      回應若出現 schema 以外的欄位，整包視為無效並改用固定模板，不會只忽略多餘欄位（REQ-AI-007）。傳給 LLM 的輸入只有原因碼與必要數值，不含姓名、傷病原文或 GPS（REQ-AI-005）。
                    </div>
                  </div>
                </Notice>
              )}
            </div>
          </Card>

          {/* ---- 28-day load ---- */}
          <Card
            title="近 28 天每日負荷"
            subtitle={`單位 ${primaryUnit ? primaryUnit.unit : "AU"}，不同單位不會相加。`}
            reqTags={["REQ-LOAD-002", "REQ-LOAD-006"]}
            actions={
              <Link className="btn btn-secondary btn-sm" to="/app/load">
                查看趨勢
              </Link>
            }
          >
            <DailyLoadChart
              points={trainingLoad.daily}
              unitLabel={primaryUnit?.unit ?? "AU"}
              height={220}
            />
          </Card>
        </div>

        <div className="stack">
          {/* ---- Today's to-do ---- */}
          <Card title="今天還沒完成" reqTags={["REQ-LOAD-004"]}>
            <div className="stack-sm">
              {todayHasRecord ? (
                <Notice tone="accent" icon="check">
                  今天已經有訓練紀錄了。
                </Notice>
              ) : todayIsRest ? (
                <Notice tone="accent" icon="check">
                  今天已標記為休息日，會計入觀測天數。
                </Notice>
              ) : (
                <>
                  <p className="field-hint">
                    沒有紀錄的一天，系統一律當作「缺漏資料」，不會自動推論為休息。只有你按下確認，才會計入觀測天數的分母。
                  </p>
                  <div className="row" style={{ gap: 8 }}>
                    <Link className="btn btn-primary btn-sm" to="/app/log">
                      記錄訓練
                    </Link>
                    <Button size="sm" icon="check" onClick={() => confirmRestDay(today)}>
                      今天是休息日
                    </Button>
                  </div>
                </>
              )}

              {pendingCount > 0 && (
                <Notice tone="warning" icon="refresh">
                  有 {pendingCount} 筆紀錄還沒送到伺服器，已安全保存在本機。
                  <Link to="/app/history" style={{ marginLeft: 6 }}>
                    查看佇列
                  </Link>
                </Notice>
              )}
            </div>
          </Card>

          {/* ---- Weather ---- */}
          <Card
            title="氣候等效配速"
            subtitle={`地點取自個人設定的城市：${weather.city}`}
            reqTags={["REQ-WEATHER-001", "REQ-WEATHER-LOCATION-001"]}
            actions={<WeatherStateBadge state={weather.state} />}
          >
            {weather.state === "UNAVAILABLE" ? (
              <Notice tone="neutral" icon="cloud">
                目前取不到天氣資料，因此不做配速換算。這裡不會用舊資料假裝是即時值。
              </Notice>
            ) : (
              <div className="stack-sm">
                <div className="row" style={{ gap: 18 }}>
                  <StatTile
                    small
                    label="氣溫"
                    value={weather.temperatureC?.toFixed(1) ?? "—"}
                    unit="°C"
                  />
                  <StatTile small label="濕度" value={`${weather.humidityPct ?? "—"}`} unit="%" />
                </div>
                <hr className="divider" />
                <div className="row-between">
                  <span className="muted">建議配速調整</span>
                  <strong className="tnum">
                    +{weather.paceAdjustmentSecPerKm} 秒 / km
                  </strong>
                </div>
                <span className="field-hint">
                  觀測時間 {weather.observedAtUtc ? formatRelative(weather.observedAtUtc) : "—"}
                  ，不使用即時定位。
                </span>
              </div>
            )}
          </Card>

          {/* ---- Body status ---- */}
          <Card
            title="身體狀況"
            actions={
              <Link className="btn btn-secondary btn-sm" to="/app/body">
                回報
              </Link>
            }
          >
            {latestInjury ? (
              <div className="stack-sm">
                <div className="row-between">
                  <span className="muted">最近一次回報</span>
                  <SeverityBadge band={latestInjury.severityBand} />
                </div>
                <div className="row-between">
                  <span className="muted">部位</span>
                  <strong>{latestInjury.bodyPart || "—"}</strong>
                </div>
                <span className="field-hint">
                  {latestInjury.localDate} 回報。自述原文另存於獨立資料表，需要單獨授權才會被讀取。
                </span>
              </div>
            ) : (
              <p className="field-hint">還沒有回報紀錄。</p>
            )}
          </Card>

          {/* ---- Recent ---- */}
          <Card
            title="最近的紀錄"
            actions={
              <Link className="btn btn-ghost btn-sm" to="/app/history">
                全部
              </Link>
            }
            flush
          >
            <ul>
              {recentActivities.map((activity) => (
                <li
                  key={activity.id}
                  style={{
                    padding: "12px 20px",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div className="row-between">
                    <div>
                      <div style={{ fontWeight: 570 }}>
                        {formatDuration(activity.durationMinutes)}
                        {activity.rpe !== null && ` · RPE ${activity.rpe}`}
                      </div>
                      <div className="field-hint">
                        {activity.localTrainingDate} · session load{" "}
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
    </>
  );
}

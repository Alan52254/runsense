import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, InfoTip, Notice, Segmented, StatTile } from "../../components/ui.tsx";
import { DailyLoadChart, LoadTrendChart } from "../../components/charts.tsx";
import { DataQualityBadge } from "../../components/domain.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import { apiConfigured } from "../../data/apiClient.ts";
import {
  computeInputSnapshotHash,
  rollingLoadSeries,
  MIN_OBSERVATION_DAYS,
} from "../../lib/trainingLoad.ts";
import { trendPointsForUnit } from "../../lib/liveTrainingLoad.ts";
import {
  formatLocalDate,
  formatNumber,
  UNIT_LABEL,
  UNIT_SHORT,
} from "../../lib/format.ts";
import type { LoadUnit } from "../../lib/types.ts";

export function TrainingLoadScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { trainingLoad, allActivities, today, preferences, liveTrend, trendStatus, refetchTrend } =
    useWorkspace();

  const units = trainingLoad.units;
  const [activeUnit, setActiveUnit] = useState<LoadUnit>(units[0]?.unit ?? "AU");
  const [view, setView] = useState<"chart" | "table">("chart");
  const [snapshotHash, setSnapshotHash] = useState<string | null>(null);
  const [showCalcDetails, setShowCalcDetails] = useState(false);

  useEffect(() => {
    if (units.length > 0 && !units.some((u) => u.unit === activeUnit)) {
      setActiveUnit(units[0].unit);
    }
  }, [units, activeUnit]);

  useEffect(() => {
    // The server already computed this hash (REQ-LOAD-007) — re-hashing it
    // client-side would just be re-deriving a number we were already given.
    if (trainingLoad.serverInputSnapshotHash) {
      setSnapshotHash(trainingLoad.serverInputSnapshotHash);
      return;
    }
    let cancelled = false;
    void computeInputSnapshotHash(trainingLoad).then((hash) => {
      if (!cancelled) setSnapshotHash(hash);
    });
    return () => {
      cancelled = true;
    };
  }, [trainingLoad]);

  const current = units.find((u) => u.unit === activeUnit) ?? units[0] ?? null;

  const trend = useMemo(() => {
    if (apiConfigured) return liveTrend ? trendPointsForUnit(liveTrend, activeUnit) : [];
    return rollingLoadSeries(allActivities, activeUnit, today, 28);
  }, [allActivities, activeUnit, today, liveTrend]);

  const dailyForUnit = useMemo(
    () =>
      trainingLoad.daily.map((point) => ({
        ...point,
        loadByUnit:
          point.loadByUnit[activeUnit] !== undefined
            ? { [activeUnit]: point.loadByUnit[activeUnit] }
            : {},
      })),
    [trainingLoad.daily, activeUnit],
  );

  const dateLabel = (value: string) => en
    ? new Intl.DateTimeFormat("en", { month: "short", day: "numeric", weekday: "short", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`))
    : formatLocalDate(value);
  const qualityReason = (reason: string) => {
    if (!en) return reason;
    if (reason.includes("兩種單位")) return "Manual and device load units both occur in this period. They cannot be summed and are shown separately.";
    if (reason.includes("未達")) return `Only ${trainingLoad.observationDays} of 28 days have a record; the threshold is ${MIN_OBSERVATION_DAYS}.`;
    if (reason.includes("負荷為 0")) return "The 28-day load is 0, so the ratio cannot be calculated.";
    return reason;
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Fitness & Fatigue" : "體能與疲勞"}</h1>
          <p className="page-desc">
            {en ? "Monitor 7-day acute load, 28-day chronic baseline, and training balance to optimize progression and recovery." : "掌握 7 天短期累積、28 天長期基準與體能負荷平衡，科學規劃每一次訓練與恢復。"}
          </p>
        </div>
      </div>

      {apiConfigured && trendStatus === "error" && (
        <Notice tone="critical" icon="alert" title={en ? "Unable to load training-load trend" : "無法載入訓練負荷趨勢"}>
          <div className="row-between" style={{ marginTop: 6 }}>
            <span>{en ? "Check your connection and try again." : "請確認網路連線後重試。"}</span>
            <Button size="sm" onClick={() => void refetchTrend()}>
              {en ? "Retry" : "重試"}
            </Button>
          </div>
        </Notice>
      )}

      {apiConfigured && trendStatus === "loading" && !liveTrend && (
        <Notice tone="neutral" icon="info">
          {en ? "Fetching training-load trend from the server…" : "正在向伺服器取得訓練負荷趨勢…"}
        </Notice>
      )}

      {units.length > 1 && (
        <Notice tone="warning" icon="alert" title={en ? "Multiple Metric Sources Detected" : "偵測到多種不同計算來源"}>
          {en ? "Manual entries and device metrics are presented separately to maintain accurate trend analysis." : "手動補登與手錶裝置數據採獨立維度呈現，確保體能分析精準可靠。"}
        </Notice>
      )}

      {trainingLoad.dataQuality === "INSUFFICIENT" && (
        <Notice tone="neutral" icon="info" title={en ? "Accumulating Baseline Data" : "正在累積基準數據"}>
          <ul className="stack-sm" style={{ marginTop: 6 }}>
            {trainingLoad.qualityReasons.map((reason) => (
              <li key={reason}>· {qualityReason(reason)}</li>
            ))}
          </ul>
          <div style={{ marginTop: 6, fontSize: 12.5, color: "var(--text-2)" }}>
            {en ? `Acute/chronic ratio unlocks after ${MIN_OBSERVATION_DAYS} days of recorded workouts.` : `持續累積達 ${MIN_OBSERVATION_DAYS} 天訓練紀錄後，系統將自動計算體能負荷比。`}
          </div>
          <Link to="/app/method" className="btn btn-ghost btn-sm" style={{ marginTop: 8 }}>
            {en ? "How this threshold works" : "了解這個門檻的計算方式"}
          </Link>
        </Notice>
      )}

      <div className="grid-4" style={{ marginBottom: 24 }}>
        <Card>
          <StatTile
            label={en ? "7-Day Acute Load" : "7 天體能負荷"}
            value={current ? formatNumber(current.acuteLoad) : "—"}
            unit={current ? UNIT_SHORT[current.unit] : undefined}
            foot={en ? `${current?.sessionCount ?? 0} sessions in last 28 days` : `近 28 天共 ${current?.sessionCount ?? 0} 次訓練`}
          />
        </Card>
        <Card>
          <StatTile
            label={en ? "28-Day Chronic Baseline" : "28 天基準負荷"}
            value={current ? formatNumber(current.chronicLoad) : "—"}
            unit={current ? UNIT_SHORT[current.unit] : undefined}
            foot={en ? "Weekly average baseline" : "換算每週平均體能基準"}
          />
        </Card>
        <Card>
          <StatTile
            label={en ? "Acute / Chronic Ratio" : "短長期負荷比"}
            value={
              current?.loadRatio === null || current === null
                ? en ? "Calculating" : "累積中"
                : current.loadRatio.toFixed(2)
            }
            foot={
              current?.loadRatio === null
                ? en ? `Unlocks at ${MIN_OBSERVATION_DAYS} days` : `需累積滿 ${MIN_OBSERVATION_DAYS} 天`
                : en ? "7-day load ÷ 28-day baseline" : "7 天負荷 ÷ 28 天基準"
            }
          />
        </Card>
        <Card>
          <StatTile
            label={en ? "Observation Days" : "有效觀測天數"}
            value={`${trainingLoad.observationDays}`}
            unit={en ? "/ 28 days" : "/ 28 天"}
            foot={<DataQualityBadge quality={trainingLoad.dataQuality} />}
          />
        </Card>
      </div>

      <Card
        title={en ? "Load trend" : "負荷趨勢"}
        actions={
          <div className="row" style={{ gap: 8 }}>
            {units.length > 1 && (
              <Segmented
                value={activeUnit}
                onChange={setActiveUnit}
                options={units.map((u) => ({ value: u.unit, label: UNIT_SHORT[u.unit] }))}
              />
            )}
            <Segmented
              value={view}
              onChange={setView}
              options={[
                { value: "chart", label: en ? "Chart" : "圖表" },
                { value: "table", label: en ? "Table" : "表格" },
              ]}
            />
          </div>
        }
      >
        {trend.length === 0 ? (
          <Notice tone="neutral" icon="info">
            {apiConfigured ? (en ? "No trend data yet." : "尚無趨勢資料。") : (en ? "No trend data to display." : "沒有可顯示的趨勢資料。")}
          </Notice>
        ) : view === "chart" ? (
          <LoadTrendChart points={trend} />
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{en ? "Date" : "日期"}</th>
                  <th className="num">{en ? "7-day load" : "7 天負荷"}</th>
                  <th className="num">{en ? "28-day weekly equivalent" : "28 天週等效"}</th>
                  <th className="num">{en ? "Ratio" : "比值"}</th>
                </tr>
              </thead>
              <tbody>
                {[...trend].reverse().map((point) => (
                  <tr key={point.localDate}>
                    <td>{dateLabel(point.localDate)}</td>
                    <td className="num">{formatNumber(point.acuteLoad)}</td>
                    <td className="num">{formatNumber(point.chronicLoad)}</td>
                    <td className="num">
                      {point.loadRatio === null ? "—" : point.loadRatio.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title={en ? `Daily training load (${activeUnit === "AU" ? "manual RPE-based" : "device-measured"})` : `每日訓練負荷（${UNIT_LABEL[activeUnit]}）`}
        subtitle={en ? "Days without a bar have no record for that day." : "沒有長條的日子代表當天沒有任何訓練紀錄。"}
      >
        <DailyLoadChart points={dailyForUnit} unitLabel={activeUnit} height={250} />
      </Card>

      <Card>
        <div className="row-between">
          <span className="switch-row-title-lg row" style={{ gap: 4, alignItems: "center" }}>
            {en ? "How the data is calculated" : "資料如何計算"}
            <InfoTip text={en ? "Open the calculation details to verify where each value comes from." : "想確認數字怎麼來的，可以在這裡查看計算細節。"} />
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setShowCalcDetails((v) => !v)}
          >
            {showCalcDetails ? (en ? "Hide details" : "收合細節") : (en ? "Show calculation details" : "顯示計算細節")}
          </button>
        </div>

        {preferences.garminSyncEnabled && (
          <div style={{ marginTop: 14 }}>
            <Notice tone="accent" icon="link">
              {en ? "Device sync is on, so your Garmin activity records are included in these numbers." : "裝置同步已開啟，你的 Garmin 訓練紀錄也會計入這些數字。"}
            </Notice>
          </div>
        )}

        {showCalcDetails && (
          <>
            <hr className="divider" style={{ margin: "14px 0" }} />
            <dl className="kv-list">
              <dt>algorithm_version</dt>
              <dd className="mono">{trainingLoad.algorithmVersion}</dd>
              <dt>schema_version</dt>
              <dd className="mono">{trainingLoad.schemaVersion}</dd>
              <dt>input_snapshot_hash</dt>
              <dd className="mono" style={{ wordBreak: "break-all" }}>
                {snapshotHash ? `sha256:${snapshotHash}` : (en ? "Calculating…" : "計算中…")}
              </dd>
              <dt>{en ? "Normalization rules" : "正規化規則"}</dt>
              <dd className="field-hint" style={{ fontWeight: 400 }}>
                {en ? "Keys sorted alphabetically · UTF-8 · timestamps normalized to UTC ISO 8601 · AU values rounded to 2 decimals · SHA-256" : "key 依字母序排序 · UTF-8 · 時間正規化為 UTC ISO 8601 · AU 類數值取小數點後 2 位 · SHA-256"}
              </dd>
            </dl>
          </>
        )}
      </Card>
    </>
  );
}

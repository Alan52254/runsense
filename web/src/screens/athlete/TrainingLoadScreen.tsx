import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, Notice, Segmented, StatTile } from "../../components/ui.tsx";
import { DailyLoadChart, LoadTrendChart } from "../../components/charts.tsx";
import { DataQualityBadge } from "../../components/domain.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { apiConfigured } from "../../data/apiClient.ts";
import {
  computeInputSnapshotHash,
  recomputeWindowFor,
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
  const { trainingLoad, allActivities, today, preferences, liveTrend, trendStatus, refetchTrend } =
    useWorkspace();

  const units = trainingLoad.units;
  const [activeUnit, setActiveUnit] = useState<LoadUnit>(units[0]?.unit ?? "AU");
  const [view, setView] = useState<"chart" | "table">("chart");
  const [snapshotHash, setSnapshotHash] = useState<string | null>(null);

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

  const recomputeExample = recomputeWindowFor(trend[trend.length - 8]?.localDate ?? today);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">訓練負荷</h1>
          <p className="page-desc">
            Phase 1 只交付「Training Load Trend」：7 天負荷、28 天週等效負荷、比值與資料品質標籤。
            這裡沒有紅黃綠燈號，也不會出現「警示」字樣。
          </p>
        </div>
      </div>

      {apiConfigured && trendStatus === "error" && (
        <Notice tone="critical" icon="alert" title="無法載入訓練負荷趨勢">
          <div className="row-between" style={{ marginTop: 6 }}>
            <span>請確認網路連線後重試。</span>
            <Button size="sm" onClick={() => void refetchTrend()}>
              重試
            </Button>
          </div>
        </Notice>
      )}

      {apiConfigured && trendStatus === "loading" && !liveTrend && (
        <Notice tone="neutral" icon="info">
          正在向伺服器取得訓練負荷趨勢…
        </Notice>
      )}

      {units.length > 1 && (
        <Notice tone="warning" icon="alert" title="這段期間有兩種不可比較的負荷單位">
          手動輸入的 AU 與裝置提供的 garmin_epoc 是兩套方法論，加總會產生沒有意義的數字。
          系統改為分開呈現趨勢，並把資料品質降為 LOW。
        </Notice>
      )}

      {trainingLoad.dataQuality === "INSUFFICIENT" && (
        <Notice tone="neutral" icon="info" title="資料不足，因此不計算比值">
          <ul className="stack-sm" style={{ marginTop: 6 }}>
            {trainingLoad.qualityReasons.map((reason) => (
              <li key={reason}>· {reason}</li>
            ))}
          </ul>
          <div style={{ marginTop: 6 }}>
            觀測天數需達 {MIN_OBSERVATION_DAYS} 天、且 28 天負荷不為 0，才會顯示 load_ratio。
          </div>
        </Notice>
      )}

      <div className="grid-4">
        <Card>
          <StatTile
            label="7 天負荷 acute_load"
            value={current ? formatNumber(current.acuteLoad) : "—"}
            unit={current ? UNIT_SHORT[current.unit] : undefined}
            foot={`${current?.sessionCount ?? 0} 次訓練納入 28 天視窗`}
          />
        </Card>
        <Card>
          <StatTile
            label="28 天週等效 chronic_load"
            value={current ? formatNumber(current.chronicLoad) : "—"}
            unit={current ? UNIT_SHORT[current.unit] : undefined}
            foot="28 天 session_load 總和 ÷ 4"
          />
        </Card>
        <Card>
          <StatTile
            label="load_ratio"
            value={
              current === null || current.loadRatio === null
                ? "不計算"
                : current.loadRatio.toFixed(2)
            }
            foot={
              current?.loadRatio === null
                ? "資料品質未達門檻"
                : "這個數字沒有對應的燈號或建議動作"
            }
          />
        </Card>
        <Card>
          <StatTile
            label="資料品質 data_quality"
            value={<DataQualityBadge quality={trainingLoad.dataQuality} />}
            small
            foot={`觀測 ${trainingLoad.observationDays} 天 · 缺漏 ${trainingLoad.missingDays} 天`}
          />
        </Card>
      </div>

      <Card
        title="負荷趨勢"
        subtitle="兩條線都是同一個 y 軸、同一個單位，沒有第二座標軸。"
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
                { value: "chart", label: "圖表" },
                { value: "table", label: "表格" },
              ]}
            />
          </div>
        }
      >
        {trend.length === 0 ? (
          <Notice tone="neutral" icon="info">
            {apiConfigured ? "尚無趨勢資料。" : "沒有可顯示的趨勢資料。"}
          </Notice>
        ) : view === "chart" ? (
          <LoadTrendChart points={trend} />
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th className="num">7 天負荷</th>
                  <th className="num">28 天週等效</th>
                  <th className="num">比值</th>
                </tr>
              </thead>
              <tbody>
                {[...trend].reverse().map((point) => (
                  <tr key={point.localDate}>
                    <td>{formatLocalDate(point.localDate)}</td>
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
        title={`每日 session load（${UNIT_LABEL[activeUnit]}）`}
        subtitle="沒有長條的日子分成兩種：你確認過的休息日，以及沒有任何資料的缺漏日。"
      >
        <DailyLoadChart points={dailyForUnit} unitLabel={activeUnit} height={250} />
      </Card>

      <div className="grid-2">
        <Card title="觀測天數怎麼算">
          <div className="stack">
            <div className="stack-sm">
              <div className="row-between">
                <span className="muted">28 天內有紀錄或已確認休息</span>
                <strong className="tnum">{trainingLoad.observationDays} 天</strong>
              </div>
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{ width: `${(trainingLoad.observationDays / 28) * 100}%` }}
                />
              </div>
              <div className="row-between field-hint">
                <span>門檻 {MIN_OBSERVATION_DAYS} 天</span>
                <span>缺漏 {trainingLoad.missingDays} 天</span>
              </div>
            </div>

            <hr className="divider" />

            <p className="field-hint">
              裝置端沒有活動事件，可能是真的休息，也可能是沒戴錶、沒同步、換了別的裝置。
              「缺席的證據」不能倒過來當成「證據的缺席」，所以這種日子一律算缺漏，不計入分母。
            </p>
          </div>
        </Card>

        <Card title="為什麼沒有紅黃綠燈號">
          <div className="stack-sm">
            <p style={{ fontSize: 13, lineHeight: 1.75 }}>
              把 ratio 對應到「安全／注意／危險」需要一組明確的門檻值。這些門檻必須有來源依據、
              版本紀錄，並經產品與運動科學顧問核准，才能出現在畫面上。
            </p>
            <p style={{ fontSize: 13, lineHeight: 1.75 }}>
              目前這些條件都還沒完成，所以 Phase 1 只顯示數字與資料品質，不做狀態判定，也不使用
              「警示」這個字。
            </p>
            <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
              <Badge>alert_state：未實作</Badge>
              <Badge>alert policy version：未核准</Badge>
            </div>
          </div>
        </Card>
      </div>

      <Card
        title="計算來源與可重現性"
        subtitle="同樣的輸入，在任何機器上都必須算出同一個雜湊值。"
      >
        <div className="stack">
          <dl className="kv-list">
            <dt>algorithm_version</dt>
            <dd className="mono">{trainingLoad.algorithmVersion}</dd>
            <dt>schema_version</dt>
            <dd className="mono">{trainingLoad.schemaVersion}</dd>
            <dt>input_snapshot_hash</dt>
            <dd className="mono" style={{ wordBreak: "break-all" }}>
              {snapshotHash ? `sha256:${snapshotHash}` : "計算中…"}
            </dd>
            <dt>正規化規則</dt>
            <dd className="field-hint" style={{ fontWeight: 400 }}>
              key 依字母序排序 · UTF-8 · 時間正規化為 UTC ISO 8601 · AU 類數值取小數點後 2 位 ·
              SHA-256
            </dd>
          </dl>

          <hr className="divider" />

          <div className="stack-sm">
            <strong style={{ fontSize: 13 }}>補登或修改過去紀錄時的重算範圍</strong>
            <p className="field-hint">
              異動發生在 {recomputeExample.fromLocalDate}，只需要重算{" "}
              {recomputeExample.fromLocalDate} 至 {recomputeExample.toLocalDate} 共{" "}
              {recomputeExample.dayCount} 天，而不是從那天一路重算到今天。
            </p>
          </div>

          {preferences.garminSyncEnabled && (
            <Notice tone="accent" icon="link">
              目前 GARMIN_ACTIVITY_SYNC_ENABLED 為開啟狀態（示範用），因此裝置來源的紀錄也被納入。
            </Notice>
          )}
        </div>
      </Card>
    </>
  );
}

import { Surface } from "../../components/Surface.tsx";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  EmptyState,
  Modal,
  Notice,
  Segmented,
} from "../../components/ui.tsx";
import { GlassPanel } from "../../components/motion.tsx";
import "../../styles/athlete.css";
import { SyncChip } from "../../components/domain.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import { apiConfigured } from "../../data/apiClient.ts";
import {
  formatDuration,
  formatLocalDate,
  formatNumber,
  formatTimeOnly,
  UNIT_SHORT,
} from "../../lib/format.ts";
import { ActivityDetailPanel } from "../../components/activityDetail.tsx";
import type { Activity } from "../../lib/types.ts";
import { Row } from "../../components/Layout.tsx";
import { Figure } from "../../components/Figure.tsx";
import { Text } from "../../components/Text.tsx";
import { historyWorkoutKind, historyWorkoutKindLabel, isAnalysableRow } from "../../lib/historyWorkoutKind.ts";
import { filterHistoryRows, type HistoryFilter } from "../../lib/historyFilter.ts";

type Filter = HistoryFilter;

export function HistoryScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { auth } = useAuth();
  const {
    allActivities,
    pendingCount,
    syncing,
    online,
    retryActivity,
    discardActivity,
    deleteActivity,
    resolveDuplicate,
    historyStatus,
    hasMoreHistory,
    loadMoreHistory,
    refetchHistory,
  } = useWorkspace();

  const [filter, setFilter] = useState<Filter>("all");
  const [duplicateTarget, setDuplicateTarget] = useState<Activity | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Activity | null>(null);
  const [deleting, setDeleting] = useState(false);
  // 查看分析 on a row: expand it and ask its detail panel to open the drawer
  const [analysisRequest, setAnalysisRequest] = useState<{ id: string; n: number } | null>(null);
  const openAnalysis = (id: string) => {
    setExpandedId(id);
    setAnalysisRequest((current) => ({ id, n: (current?.n ?? 0) + 1 }));
  };

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";
  const localDateLabel = (value: string) => en
    ? new Intl.DateTimeFormat("en", { month: "short", day: "numeric", weekday: "short", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`))
    : formatLocalDate(value);
  const durationLabel = (minutes: number) => formatDuration(minutes, locale);

  const duplicates = allActivities.filter((a) => a.duplicateCandidateOf !== null);
  const failed = allActivities.filter(
    (a) => a.syncState === "FAILED_RETRYABLE" || a.syncState === "FAILED_TERMINAL",
  );

  const rows = useMemo(() => filterHistoryRows(allActivities, filter), [allActivities, filter]);
  const analysableCount = useMemo(() => allActivities.filter(isAnalysableRow).length, [allActivities]);

  const original = duplicateTarget
    ? allActivities.find((a) => a.id === duplicateTarget.duplicateCandidateOf)
    : null;

  const summaryStats = useMemo(() => {
    let peakHr = 0;
    let totalCad = 0;
    let cadCount = 0;
    let totalClimb = 0;
    let totalCals = 0;
    let totalDist = 0;

    for (const a of allActivities) {
      const m = a.deviceMetrics;
      if (a.distanceKm) totalDist += a.distanceKm;
      if (m?.maxHeartRate && m.maxHeartRate > peakHr) peakHr = m.maxHeartRate;
      if (m?.avgHeartRate && m.avgHeartRate > peakHr) peakHr = m.avgHeartRate;
      if (m?.avgCadenceStepsPerMin) {
        totalCad += m.avgCadenceStepsPerMin;
        cadCount++;
      }
      if (m?.elevationGainM) totalClimb += m.elevationGainM;
      if (m?.calories) totalCals += m.calories;
    }

    return {
      peakHr: peakHr > 0 ? peakHr : "—",
      avgCad: cadCount > 0 ? Math.round(totalCad / cadCount) : "—",
      totalClimb: totalClimb > 0 ? totalClimb : "—",
      totalCals: totalCals > 0 ? totalCals : "—",
      totalDist: totalDist > 0 ? totalDist.toFixed(1) : "—",
    };
  }, [allActivities]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Activity Log" : "歷程回顧"}</h1>
          <p className="page-desc">
            {en ? "Track all your completed workouts, pace, duration, and fitness load in one place." : "記錄你每一次邁步的足跡、配速、時長與體能負荷。"}
          </p>
        </div>
        <Link className="btn btn-secondary" to="/app/log">
          <Icon name="shoe" size={17} />
          {en ? "Log Workout" : "手動補登"}
        </Link>
      </div>

      <div className="ath-hist-stats">
        {[
          { icon: "heart" as const, label: en ? "Peak Heart Rate" : "歷史最高心率", value: summaryStats.peakHr, unit: "bpm", foot: en ? "Highest across loaded workouts" : "已載入紀錄中的最高值" },
          { icon: "activity" as const, label: en ? "Avg Cadence" : "平均步頻", value: summaryStats.avgCad, unit: "spm", foot: en ? "Optimal running rhythm" : "穩定跑步節奏" },
          { icon: "mountain" as const, label: en ? "Total Elevation Gain" : "累計爬升高度", value: summaryStats.totalClimb, unit: "m", foot: en ? "Vertical climbing" : "肌耐力地形爬升" },
          { icon: "energy" as const, label: en ? "Energy Burned" : "累計能量消耗", value: summaryStats.totalCals, unit: "kcal", foot: en ? `Distance: ${summaryStats.totalDist} km` : `總跑量: ${summaryStats.totalDist} km` },
        ].map((stat) => (
          <GlassPanel key={stat.label} variant="inner" padding="sm" className="ath-hist-stat">
            <span className="ath-hist-stat-label"><Icon name={stat.icon} size={16} />{stat.label}</span>
            <span className="ath-hist-stat-value tnum">
              {typeof stat.value === "number" ? stat.value.toLocaleString() : stat.value}
              {typeof stat.value === "number" && <small>{stat.unit}</small>}
            </span>
            <span className="ath-hist-stat-foot">{stat.foot}</span>
          </GlassPanel>
        ))}
      </div>

      {apiConfigured && historyStatus === "error" && (
        <Notice tone="critical" icon="alert" title={en ? "Unable to load activity history" : "無法載入訓練紀錄"}>
          <Row justify="between" gap={3}>
            <span>{en ? "Check your connection and try again." : "請確認網路連線後重試。"}</span>
            <Button size="sm" onClick={() => void refetchHistory()}>
              {en ? "Retry" : "重試"}
            </Button>
          </Row>
        </Notice>
      )}

      {pendingCount > 0 && !online && (
        <Notice tone="warning" icon="wifi-off" title={en ? "Offline Queue Active" : "離線佇列運作中"}>
          {en ? "Records are saved locally and will sync automatically once back online." : "訓練紀錄已安全儲存於本機，連線後自動同步。"}
        </Notice>
      )}

      {duplicates.length > 0 && (
        <Notice tone="accent" icon="alert" title={en ? `${duplicates.length} duplicate entries need review` : `${duplicates.length} 筆疑似重複紀錄，請確認`}>
          {en ? "Review potential duplicate records from multiple sources." : "檢視不同來源的潛在重複紀錄，確保體能計算不失真。"}
        </Notice>
      )}

      <GlassPanel as="section" className="ath-panel ath-hist-panel" padding="none" aria-label={en ? "Activity list" : "訓練紀錄清單"}>
        <div className="ath-hist-toolbar">
          <h2 className="ath-panel-title">
            {en ? `${rows.length} record${rows.length === 1 ? "" : "s"}` : `共 ${rows.length} 筆`}
          </h2>
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: en ? "All" : "全部" },
              { value: "pending", label: `${en ? "Pending" : "待同步"} ${pendingCount}` },
              { value: "failed", label: `${en ? "Failed" : "失敗"} ${failed.length}` },
              { value: "duplicate", label: `${en ? "Duplicates" : "疑似重複"} ${duplicates.length}` },
              { value: "analysable", label: `${en ? "Analysable" : "可分析"} ${analysableCount}` },
            ]}
          />
        </div>
        {rows.length === 0 && apiConfigured && historyStatus === "loading" ? (
          <EmptyState icon="history" title={en ? "Loading…" : "載入中…"} description={en ? "Fetching activity history from the server." : "正在向伺服器取得訓練紀錄。"} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon="history"
            title={en ? "No records match this filter" : "這個篩選條件下沒有紀錄"}
            description={en ? "Choose another filter or log a workout first." : "換一個篩選條件，或先記錄一次訓練。"}
            action={
              <Link className="btn btn-primary btn-sm" to="/app/log">
                {en ? "Log workout" : "記錄訓練"}
              </Link>
            }
          />
        ) : (
          <ul className="ath-hist-list">
            {rows.map((activity) => {
              const expanded = expandedId === activity.id;
              const m = activity.deviceMetrics;
              const paceSec = activity.distanceKm && activity.distanceKm > 0
                ? Math.round((activity.durationMinutes * 60) / activity.distanceKm)
                : null;
              const avgHr = m?.avgHeartRate;
              const avgCad = m?.avgCadenceStepsPerMin;
              const detailId = `hist-detail-${activity.id}`;
              const kind = historyWorkoutKind(activity.structure);
              const analysable = isAnalysableRow(activity);
              return (
                <li key={activity.id} className={`ath-hist-row${expanded ? " is-open" : ""}`}>
                  <button
                    type="button"
                    className="ath-hist-main"
                    aria-expanded={expanded}
                    aria-controls={expanded ? detailId : undefined}
                    onClick={() => setExpandedId((current) => (current === activity.id ? null : activity.id))}
                  >
                    <span className="ath-hist-cell ath-hist-date">
                      <span className="ath-hist-date-line">
                        <strong>{localDateLabel(activity.localTrainingDate)}</strong>
                        {kind && (
                          <span className="ath-hist-kind" data-kind={kind}>
                            {historyWorkoutKindLabel(kind, locale)}
                          </span>
                        )}
                      </span>
                      <small className="tnum">{formatTimeOnly(activity.performedAtUtc, activity.timezoneSnapshot || timezone)}</small>
                    </span>
                    <span className="ath-hist-cell ath-hist-dist">
                      <strong><Figure kind="distance" meters={activity.distanceKm ? activity.distanceKm * 1000 : null} /></strong>
                      <small><Figure kind="pace" secPerKm={paceSec} /></small>
                    </span>
                    <span className="ath-hist-cell ath-hist-dur">
                      <strong className="tnum">{durationLabel(activity.durationMinutes)}</strong>
                      <small className="tnum">
                        {formatNumber(activity.sessionLoad)} {UNIT_SHORT[activity.unit]}
                      </small>
                    </span>
                    <span className="ath-hist-cell ath-hist-body">
                      <strong className="tnum">{avgHr !== undefined ? `${avgHr} bpm` : "—"}</strong>
                      <small className="tnum">{avgCad !== undefined ? `${avgCad} spm` : "—"}</small>
                    </span>
                  </button>
                  <div className="ath-hist-side">
                    {analysable && (
                      <Button size="sm" variant="secondary" icon="activity" onClick={() => openAnalysis(activity.id)}>
                        {en ? "View analysis" : "查看分析"}
                      </Button>
                    )}
                    {activity.syncState !== "SYNCED" && (
                      <div className="ath-hist-sync">
                        <SyncChip state={activity.syncState} />
                        {activity.lastErrorCode && (
                          <div className="field-hint">
                            <code className="mono">{activity.lastErrorCode}</code> · {activity.syncAttempts} {en ? "attempts" : "次嘗試"}
                          </div>
                        )}
                      </div>
                    )}
                    {activity.duplicateCandidateOf && (
                      <Button size="sm" onClick={() => setDuplicateTarget(activity)}>
                        {en ? "Review" : "處理"}
                      </Button>
                    )}
                    {(activity.syncState === "FAILED_RETRYABLE" || activity.syncState === "LOCAL_ONLY") && (
                      <Button size="sm" icon="refresh" disabled={syncing || !online} onClick={() => void retryActivity(activity.id)}>
                        {en ? "Retry" : "重試"}
                      </Button>
                    )}
                  </div>
                  {expanded && (
                    <div className="ath-hist-detail" id={detailId}>
                      <Row justify="between" gap={3} className="ath-hist-detail-bar">
                        {activity.provider === "manual" ? (
                          <Badge>{en ? "Manual" : "手動輸入"}</Badge>
                        ) : (
                          <Badge>Garmin</Badge>
                        )}
                        <Row gap={2}>
                          {activity.syncState === "FAILED_TERMINAL" && (
                            <Button size="sm" variant="ghost" icon="trash" className="ath-hist-del" aria-label={en ? "Delete" : "刪除"} title={en ? "Delete" : "刪除"} onClick={() => discardActivity(activity.id)} />
                          )}
                          {activity.syncState === "SYNCED" && (
                            <Button size="sm" variant="ghost" icon="trash" className="ath-hist-del" aria-label={en ? "Delete" : "刪除"} title={en ? "Delete" : "刪除"} onClick={() => setDeleteTarget(activity)} />
                          )}
                          <Button size="sm" variant="ghost" icon="chevron-up" className="ath-hist-del" aria-label={en ? "Collapse" : "收合"} title={en ? "Collapse" : "收合"} onClick={() => setExpandedId(null)} />
                        </Row>
                      </Row>
                      <ActivityDetailPanel
                        activity={activity}
                        locale={locale}
                        analysisRequest={analysisRequest?.id === activity.id ? analysisRequest.n : 0}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {apiConfigured && hasMoreHistory && (
          <Row justify="center" className="ath-hist-more">
            <Button onClick={() => void loadMoreHistory()} disabled={historyStatus === "loading"}>
              {historyStatus === "loading" ? (en ? "Loading…" : "載入中…") : (en ? "Load more" : "載入更多")}
            </Button>
          </Row>
        )}
      </GlassPanel>

      <Modal
        open={duplicateTarget !== null}
        title={en ? "Are these the same workout?" : "這是同一場訓練嗎？"}
        description={en ? "RunSense found two records with similar time and distance but different source IDs. You decide how to handle them." : "系統偵測到時間與距離相近、但來源識別碼不同的兩筆紀錄。要怎麼處理由你決定。"}
        onClose={() => setDuplicateTarget(null)}
        footer={
          <>
            <Button onClick={() => setDuplicateTarget(null)}>{en ? "Decide later" : "稍後再說"}</Button>
            <Button
              onClick={() => {
                if (duplicateTarget) resolveDuplicate(duplicateTarget.id, "keep_both");
                setDuplicateTarget(null);
              }}
            >
              {en ? "Keep both workouts" : "是兩場不同的訓練"}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (duplicateTarget) resolveDuplicate(duplicateTarget.id, "mark_duplicate");
                setDuplicateTarget(null);
              }}
            >
              {en ? "Mark as duplicate" : "確認為重複"}
            </Button>
          </>
        }
      >
        {duplicateTarget && (
          <div className="stack">
            <div className="grid-2">
              {[original, duplicateTarget].map((activity, index) =>
                activity ? (
                  <Surface depth="inner" padding="sm"
                    key={activity.id}
                  >
                    <Row justify="between" className="ath-dup-head">
                      <Text variant="label" as="strong">
                        {index === 0 ? (en ? "Existing record" : "原有紀錄") : (en ? "New record" : "新進紀錄")}
                      </Text>
                      <Badge>{activity.provider === "manual" ? (en ? "Manual" : "手動輸入") : "Garmin"}</Badge>
                    </Row>
                    <dl className="kv-list">
                      <dt>{en ? "Date" : "日期"}</dt>
                      <dd>{activity.localTrainingDate}</dd>
                      <dt>{en ? "Time" : "時間"}</dt>
                      <dd>{formatTimeOnly(activity.performedAtUtc, activity.timezoneSnapshot || timezone)}</dd>
                      <dt>{en ? "Duration" : "時長"}</dt>
                      <dd>{durationLabel(activity.durationMinutes)}</dd>
                      <dt>{en ? "Distance" : "距離"}</dt>
                      <dd><Figure kind="distance" meters={activity.distanceKm ? activity.distanceKm * 1000 : null} /></dd>
                      <dt>{en ? "Load" : "負荷"}</dt>
                      <dd>
                        {formatNumber(activity.sessionLoad)} {UNIT_SHORT[activity.unit]}
                      </dd>
                    </dl>
                  </Surface>
                ) : null,
              )}
            </div>
            <Notice tone="neutral" icon="info">
              {en ? "Neither choice deletes source data. Marking a duplicate only adds an annotation; originals remain in athlete_annotations." : "不論你選哪一個，系統都不會刪除原始資料。選擇「確認為重複」只是加上標記，原始版本會保留在 athlete_annotations 供日後查閱。"}
            </Notice>
          </div>
        )}
      </Modal>

      <Modal
        open={deleteTarget !== null}
        title={en ? "Delete this record?" : "要刪除這筆紀錄嗎？"}
        description={
          en
            ? "It will disappear from your history and no longer count toward training load."
            : "這筆紀錄會從你的歷程回顧與體能負荷計算中移除，且無法復原。"
        }
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Button onClick={() => setDeleteTarget(null)} disabled={deleting}>
              {en ? "Cancel" : "取消"}
            </Button>
            <Button
              variant="danger"
              disabled={deleting}
              onClick={async () => {
                if (!deleteTarget) return;
                setDeleting(true);
                const ok = await deleteActivity(deleteTarget.id);
                setDeleting(false);
                if (ok) setDeleteTarget(null);
              }}
            >
              {deleting ? (en ? "Deleting…" : "刪除中…") : en ? "Delete" : "刪除"}
            </Button>
          </>
        }
      >
        {deleteTarget && (
          <dl className="kv-list">
            <dt>{en ? "Date" : "日期"}</dt>
            <dd>{localDateLabel(deleteTarget.localTrainingDate)}</dd>
            <dt>{en ? "Source" : "來源"}</dt>
            <dd>{deleteTarget.provider === "manual" ? (en ? "Manual" : "手動輸入") : "Garmin"}</dd>
            <dt>{en ? "Duration" : "時長"}</dt>
            <dd>{durationLabel(deleteTarget.durationMinutes)}</dd>
          </dl>
        )}
      </Modal>
    </>
  );
}

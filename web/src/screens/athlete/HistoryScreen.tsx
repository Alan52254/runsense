import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Modal,
  Notice,
  Segmented,
} from "../../components/ui.tsx";
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
  formatPace,
  formatTimeOnly,
  UNIT_SHORT,
} from "../../lib/format.ts";
import { WorkoutStructureView, assignmentSegmentToDisplay } from "../../components/workoutStructure.tsx";
import type { Activity } from "../../lib/types.ts";

/** heart rate / pace / cadence / elevation / calories / training effect /
 *  structure, whatever a row happens to have -- distance+RPE-only manual
 *  entries will have none of this, device-imported history usually has
 *  most of it. */
function ActivityDetailPanel({ activity, locale }: { activity: Activity; locale: "zh-TW" | "en" }) {
  const en = locale === "en";
  const [expandedSegmentKey, setExpandedSegmentKey] = useState<string | null>(null);
  const m = activity.deviceMetrics;
  const paceSecPerKm =
    activity.distanceKm && activity.distanceKm > 0
      ? (activity.durationMinutes * 60) / activity.distanceKm
      : null;

  const stats: { label: string; value: string }[] = [];
  if (activity.distanceKm) stats.push({ label: en ? "Distance" : "距離", value: `${activity.distanceKm} km` });
  if (paceSecPerKm !== null) stats.push({ label: en ? "Avg pace" : "平均配速", value: formatPace(paceSecPerKm) });
  if (m.avgHeartRate !== undefined)
    stats.push({
      label: en ? "Heart rate" : "心率",
      value: m.maxHeartRate !== undefined ? `${m.avgHeartRate} / ${m.maxHeartRate} bpm` : `${m.avgHeartRate} bpm`,
    });
  if (m.avgCadenceStepsPerMin !== undefined)
    stats.push({ label: en ? "Cadence" : "步頻", value: `${m.avgCadenceStepsPerMin} spm` });
  if (m.avgStrideLengthM !== undefined)
    stats.push({ label: en ? "Stride length" : "步幅", value: `${m.avgStrideLengthM} m` });
  if (m.elevationGainM !== undefined || m.elevationLossM !== undefined)
    stats.push({
      label: en ? "Elevation" : "海拔爬升／下降",
      value: `${en ? "+" : "↑"}${m.elevationGainM ?? 0} / ${en ? "-" : "↓"}${m.elevationLossM ?? 0} m`,
    });
  if (m.calories !== undefined) stats.push({ label: en ? "Calories" : "熱量", value: `${m.calories} kcal` });
  if (m.aerobicTrainingEffect !== undefined)
    stats.push({
      label: en ? "Training effect" : "訓練效果",
      value: `${m.aerobicTrainingEffect}${m.anaerobicTrainingEffect ? ` / ${m.anaerobicTrainingEffect}` : ""}${m.trainingEffectLabel ? ` (${m.trainingEffectLabel})` : ""}`,
    });

  const hasStructure = activity.structure.length > 0;

  if (stats.length === 0 && !hasStructure) {
    return (
      <div className="field-hint" style={{ padding: "12px 4px" }}>
        {en ? "No further detail for this record." : "這筆紀錄沒有更多詳細資料。"}
      </div>
    );
  }

  return (
    <div className="stack-sm" style={{ padding: "12px 4px" }}>
      {stats.length > 0 && (
        <div className="grid-4" style={{ gap: 10 }}>
          {stats.map((s) => (
            <div key={s.label}>
              <div className="field-hint" style={{ fontSize: 11 }}>{s.label}</div>
              <div className="tnum" style={{ fontSize: 14, fontWeight: 600 }}>{s.value}</div>
            </div>
          ))}
        </div>
      )}
      {hasStructure && (
        <WorkoutStructureView
          segments={activity.structure.map((segment, index) => assignmentSegmentToDisplay(segment, index, locale))}
          heading={en ? "Workout structure" : "課表結構"}
          expandedKey={expandedSegmentKey}
          onToggleExpand={(key) => setExpandedSegmentKey((current) => (current === key ? null : key))}
        />
      )}
    </div>
  );
}

type Filter = "all" | "pending" | "failed" | "duplicate";

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

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";
  const localDateLabel = (value: string) => en
    ? new Intl.DateTimeFormat("en", { month: "short", day: "numeric", weekday: "short", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`))
    : formatLocalDate(value);
  const durationLabel = (minutes: number) => en
    ? `${Math.floor(minutes / 60) > 0 ? `${Math.floor(minutes / 60)} hr ` : ""}${minutes % 60} min`
    : formatDuration(minutes);

  const duplicates = allActivities.filter((a) => a.duplicateCandidateOf !== null);
  const failed = allActivities.filter(
    (a) => a.syncState === "FAILED_RETRYABLE" || a.syncState === "FAILED_TERMINAL",
  );

  const rows = useMemo(() => {
    if (filter === "pending")
      return allActivities.filter(
        (a) => a.syncState === "LOCAL_ONLY" || a.syncState === "SYNCING",
      );
    if (filter === "failed") return failed;
    if (filter === "duplicate") return duplicates;
    return allActivities;
  }, [allActivities, duplicates, failed, filter]);

  const original = duplicateTarget
    ? allActivities.find((a) => a.id === duplicateTarget.duplicateCandidateOf)
    : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Activity Log" : "歷程回顧"}</h1>
          <p className="page-desc">
            {en ? "Track all your completed workouts, pace, duration, and fitness load in one place." : "記錄你每一次邁步的足跡、配速、時長與體能負荷。"}
          </p>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <Link className="btn btn-primary" to="/app/run">
            <Icon name="runner" size={17} />
            {en ? "Run Now" : "出發開跑！"}
          </Link>
          <Link className="btn btn-secondary" to="/app/log">
            <Icon name="shoe" size={17} />
            {en ? "Log Workout" : "手動補登"}
          </Link>
          <Link className="btn btn-secondary" to="/app/import">
            <Icon name="download" size={17} />
            {en ? "Import Garmin CSV" : "匯入 Garmin CSV"}
          </Link>
        </div>
      </div>

      {apiConfigured && historyStatus === "error" && (
        <Notice tone="critical" icon="alert" title={en ? "Unable to load activity history" : "無法載入訓練紀錄"}>
          <div className="row-between" style={{ marginTop: 6 }}>
            <span>{en ? "Check your connection and try again." : "請確認網路連線後重試。"}</span>
            <Button size="sm" onClick={() => void refetchHistory()}>
              {en ? "Retry" : "重試"}
            </Button>
          </div>
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

      <Card
        title={en ? `${rows.length} record${rows.length === 1 ? "" : "s"}` : `共 ${rows.length} 筆`}
        actions={
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: en ? "All" : "全部" },
              { value: "pending", label: `${en ? "Pending" : "待同步"} ${pendingCount}` },
              { value: "failed", label: `${en ? "Failed" : "失敗"} ${failed.length}` },
              { value: "duplicate", label: `${en ? "Duplicates" : "疑似重複"} ${duplicates.length}` },
            ]}
          />
        }
        flush
      >
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
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th />
                  <th>{en ? "Date" : "日期"}</th>
                  <th>{en ? "Time" : "時間"}</th>
                  <th>{en ? "Source" : "來源"}</th>
                  <th className="num">{en ? "Duration" : "時長"}</th>
                  <th className="num">RPE</th>
                  <th className="num">session_load</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((activity) => {
                  const expanded = expandedId === activity.id;
                  return (
                    <Fragment key={activity.id}>
                      <tr
                        className="is-clickable"
                        onClick={() => setExpandedId((current) => (current === activity.id ? null : activity.id))}
                      >
                        <td style={{ width: 28 }}>
                          <Icon name={expanded ? "chevron-up" : "chevron-down"} size={14} />
                        </td>
                        <td>
                          <div style={{ fontWeight: 560 }}>
                            {localDateLabel(activity.localTrainingDate)}
                          </div>
                          {activity.note && (
                            <div className="field-hint" style={{ maxWidth: 300 }}>
                              {activity.note}
                            </div>
                          )}
                        </td>
                        <td className="muted">
                          {formatTimeOnly(activity.performedAtUtc, timezone)}
                        </td>
                        <td>
                          {activity.provider === "manual" ? (
                            <Badge>{en ? "Manual" : "手動輸入"}</Badge>
                          ) : (
                            <Badge tone="accent">Garmin</Badge>
                          )}
                          {activity.duplicateCandidateOf && (
                            <span style={{ marginLeft: 6 }}>
                              <Badge tone="warning" dot>
                                {en ? "Possible duplicate" : "疑似重複"}
                              </Badge>
                            </span>
                          )}
                        </td>
                        <td className="num">{durationLabel(activity.durationMinutes)}</td>
                        <td className="num">{activity.rpe ?? "—"}</td>
                        <td className="num">
                          {formatNumber(activity.sessionLoad)}{" "}
                          <span className="dim">{UNIT_SHORT[activity.unit]}</span>
                        </td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                            {activity.syncState !== "SYNCED" && (
                              <div style={{ textAlign: "right" }}>
                                <SyncChip state={activity.syncState} />
                                {activity.lastErrorCode && (
                                  <div className="field-hint">
                                    <code className="mono">{activity.lastErrorCode}</code> ·{" "}
                                    {activity.syncAttempts} {en ? "attempts" : "次嘗試"}
                                  </div>
                                )}
                              </div>
                            )}
                            {activity.duplicateCandidateOf && (
                              <Button size="sm" onClick={() => setDuplicateTarget(activity)}>
                                {en ? "Review" : "處理"}
                              </Button>
                            )}
                            {(activity.syncState === "FAILED_RETRYABLE" ||
                              activity.syncState === "LOCAL_ONLY") && (
                              <Button
                                size="sm"
                                icon="refresh"
                                disabled={syncing || !online}
                                onClick={() => void retryActivity(activity.id)}
                              >
                                {en ? "Retry" : "重試"}
                              </Button>
                            )}
                            {activity.syncState === "FAILED_TERMINAL" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon="trash"
                                onClick={() => discardActivity(activity.id)}
                              >
                                {en ? "Delete" : "刪除"}
                              </Button>
                            )}
                            {activity.syncState === "SYNCED" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon="trash"
                                onClick={() => setDeleteTarget(activity)}
                              >
                                {en ? "Delete" : "刪除"}
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={8} style={{ background: "var(--surface-2)" }}>
                            <ActivityDetailPanel activity={activity} locale={locale} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {apiConfigured && hasMoreHistory && (
          <div className="row" style={{ justifyContent: "center", padding: "14px 0" }}>
            <Button
              onClick={() => void loadMoreHistory()}
              disabled={historyStatus === "loading"}
            >
              {historyStatus === "loading" ? (en ? "Loading…" : "載入中…") : (en ? "Load more" : "載入更多")}
            </Button>
          </div>
        )}
      </Card>

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
                  <div
                    key={activity.id}
                    className="card"
                    style={{ padding: 14, boxShadow: "none" }}
                  >
                    <div className="row-between" style={{ marginBottom: 8 }}>
                      <strong style={{ fontSize: 13 }}>
                        {index === 0 ? (en ? "Existing record" : "原有紀錄") : (en ? "New record" : "新進紀錄")}
                      </strong>
                      <Badge>{activity.provider === "manual" ? (en ? "Manual" : "手動輸入") : "Garmin"}</Badge>
                    </div>
                    <dl className="kv-list">
                      <dt>{en ? "Date" : "日期"}</dt>
                      <dd>{activity.localTrainingDate}</dd>
                      <dt>{en ? "Time" : "時間"}</dt>
                      <dd>{formatTimeOnly(activity.performedAtUtc, timezone)}</dd>
                      <dt>{en ? "Duration" : "時長"}</dt>
                      <dd>{durationLabel(activity.durationMinutes)}</dd>
                      <dt>{en ? "Distance" : "距離"}</dt>
                      <dd>{activity.distanceKm ? `${activity.distanceKm} km` : "—"}</dd>
                      <dt>{en ? "Load" : "負荷"}</dt>
                      <dd>
                        {formatNumber(activity.sessionLoad)} {UNIT_SHORT[activity.unit]}
                      </dd>
                    </dl>
                  </div>
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

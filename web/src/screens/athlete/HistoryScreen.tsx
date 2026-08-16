import { useMemo, useState } from "react";
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
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { apiConfigured } from "../../data/apiClient.ts";
import {
  formatDuration,
  formatLocalDate,
  formatNumber,
  formatTimeOnly,
  UNIT_SHORT,
} from "../../lib/format.ts";
import type { Activity } from "../../lib/types.ts";

type Filter = "all" | "pending" | "failed" | "duplicate";

export function HistoryScreen() {
  const { auth } = useAuth();
  const {
    allActivities,
    pendingCount,
    syncing,
    online,
    syncNow,
    retryActivity,
    discardActivity,
    resolveDuplicate,
    historyStatus,
    hasMoreHistory,
    loadMoreHistory,
    refetchHistory,
  } = useWorkspace();

  const [filter, setFilter] = useState<Filter>("all");
  const [duplicateTarget, setDuplicateTarget] = useState<Activity | null>(null);

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";

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
          <h1 className="page-title">訓練紀錄</h1>
          <p className="page-desc">
            這裡的每一筆都是你本人擁有的正典紀錄（athlete-owned），沒有 team_id 欄位。
            團隊看得到哪些，取決於你在「團隊與授權」的設定。
          </p>
        </div>
        <div className="req-tag-row">
          <span className="req-tag">REQ-DATAOWN-001</span>
          <span className="req-tag">REQ-SYNC-002</span>
        </div>
      </div>

      {apiConfigured && historyStatus === "error" && (
        <Notice tone="critical" icon="alert" title="無法載入訓練紀錄">
          <div className="row-between" style={{ marginTop: 6 }}>
            <span>請確認網路連線後重試。</span>
            <Button size="sm" onClick={() => void refetchHistory()}>
              重試
            </Button>
          </div>
        </Notice>
      )}

      {pendingCount > 0 && (
        <Notice tone="warning" icon="refresh" title={`${pendingCount} 筆等待同步`}>
          <div className="row-between" style={{ marginTop: 6 }}>
            <span>
              這些紀錄已安全保存在本機。恢復連線後，目標是 95% 的佇列紀錄在 30 秒內完成同步。
            </span>
            <Button size="sm" variant="primary" onClick={() => void syncNow()} disabled={syncing || !online}>
              {syncing ? "同步中…" : "立即同步"}
            </Button>
          </div>
        </Notice>
      )}

      {duplicates.length > 0 && (
        <Notice tone="accent" icon="alert" title={`${duplicates.length} 筆疑似重複，等你確認`}>
          系統只標記 duplicate_candidate，不會自動刪除或合併。就算你選擇合併，原始版本也會保留在
          athlete_annotations。
          <span className="req-tag" style={{ marginLeft: 6 }}>
            REQ-DEDUP-002
          </span>
        </Notice>
      )}

      <Card
        title={`共 ${rows.length} 筆`}
        actions={
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "全部" },
              { value: "pending", label: `待同步 ${pendingCount}` },
              { value: "failed", label: `失敗 ${failed.length}` },
              { value: "duplicate", label: `疑似重複 ${duplicates.length}` },
            ]}
          />
        }
        flush
      >
        {rows.length === 0 && apiConfigured && historyStatus === "loading" ? (
          <EmptyState icon="history" title="載入中…" description="正在向伺服器取得訓練紀錄。" />
        ) : rows.length === 0 ? (
          <EmptyState
            icon="history"
            title="這個篩選條件下沒有紀錄"
            description="換一個篩選條件，或先記錄一次訓練。"
            action={
              <Link className="btn btn-primary btn-sm" to="/app/log">
                記錄訓練
              </Link>
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>時間</th>
                  <th>來源</th>
                  <th className="num">時長</th>
                  <th className="num">RPE</th>
                  <th className="num">session_load</th>
                  <th>同步狀態</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((activity) => (
                  <tr key={activity.id}>
                    <td>
                      <div style={{ fontWeight: 560 }}>
                        {formatLocalDate(activity.localTrainingDate)}
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
                        <Badge>手動輸入</Badge>
                      ) : (
                        <Badge tone="accent">Garmin</Badge>
                      )}
                      {activity.duplicateCandidateOf && (
                        <span style={{ marginLeft: 6 }}>
                          <Badge tone="warning" dot>
                            疑似重複
                          </Badge>
                        </span>
                      )}
                    </td>
                    <td className="num">{formatDuration(activity.durationMinutes)}</td>
                    <td className="num">{activity.rpe ?? "—"}</td>
                    <td className="num">
                      {formatNumber(activity.sessionLoad)}{" "}
                      <span className="dim">{UNIT_SHORT[activity.unit]}</span>
                    </td>
                    <td>
                      <SyncChip state={activity.syncState} />
                      {activity.lastErrorCode && (
                        <div className="field-hint">
                          <code className="mono">{activity.lastErrorCode}</code> ·{" "}
                          {activity.syncAttempts} 次嘗試
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                        {activity.duplicateCandidateOf && (
                          <Button size="sm" onClick={() => setDuplicateTarget(activity)}>
                            處理
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
                            重試
                          </Button>
                        )}
                        {activity.syncState === "FAILED_TERMINAL" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            icon="trash"
                            onClick={() => discardActivity(activity.id)}
                          >
                            刪除
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
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
              {historyStatus === "loading" ? "載入中…" : "載入更多"}
            </Button>
          </div>
        )}
      </Card>

      <Card title="同步狀態的意思" reqTags={["REQ-SYNC-001", "REQ-SYNC-003"]}>
        <div className="grid-3">
          {(
            [
              ["LOCAL_ONLY", "已寫入本機並提交，還沒送到伺服器。這個狀態不代表資料有風險。"],
              ["SYNCING", "正在送出。"],
              ["SYNCED", "伺服器已確認，並回傳 server_version。"],
              ["FAILED_RETRYABLE", "網路或 5xx 錯誤，會自動重試。"],
              ["FAILED_TERMINAL", "4xx 回應，重送同樣內容不會成功，需要你處理。"],
            ] as const
          ).map(([state, desc]) => (
            <div key={state} className="stack-sm">
              <SyncChip state={state} />
              <span className="field-hint">
                <code className="mono">{state}</code> — {desc}
              </span>
            </div>
          ))}
        </div>
      </Card>

      <Modal
        open={duplicateTarget !== null}
        title="這是同一場訓練嗎？"
        description="系統偵測到時間與距離相近、但來源識別碼不同的兩筆紀錄。要怎麼處理由你決定。"
        onClose={() => setDuplicateTarget(null)}
        footer={
          <>
            <Button onClick={() => setDuplicateTarget(null)}>稍後再說</Button>
            <Button
              onClick={() => {
                if (duplicateTarget) resolveDuplicate(duplicateTarget.id, "keep_both");
                setDuplicateTarget(null);
              }}
            >
              是兩場不同的訓練
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (duplicateTarget) resolveDuplicate(duplicateTarget.id, "mark_duplicate");
                setDuplicateTarget(null);
              }}
            >
              確認為重複
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
                        {index === 0 ? "原有紀錄" : "新進紀錄"}
                      </strong>
                      <Badge>{activity.provider === "manual" ? "手動輸入" : "Garmin"}</Badge>
                    </div>
                    <dl className="kv-list">
                      <dt>日期</dt>
                      <dd>{activity.localTrainingDate}</dd>
                      <dt>時間</dt>
                      <dd>{formatTimeOnly(activity.performedAtUtc, timezone)}</dd>
                      <dt>時長</dt>
                      <dd>{formatDuration(activity.durationMinutes)}</dd>
                      <dt>距離</dt>
                      <dd>{activity.distanceKm ? `${activity.distanceKm} km` : "—"}</dd>
                      <dt>負荷</dt>
                      <dd>
                        {formatNumber(activity.sessionLoad)} {UNIT_SHORT[activity.unit]}
                      </dd>
                    </dl>
                  </div>
                ) : null,
              )}
            </div>
            <Notice tone="neutral" icon="info">
              不論你選哪一個，系統都不會刪除原始資料。選擇「確認為重複」只是加上標記，原始版本會保留在
              athlete_annotations 供日後查閱。
            </Notice>
          </div>
        )}
      </Modal>
    </>
  );
}

import { Badge, Button, Card, Notice, SwitchRow } from "../../../components/ui.tsx";
import { Icon } from "../../../components/Icon.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";

/** REQ-GARMIN-002: the flag stays off until every one of these is done. */
const GARMIN_PRECONDITIONS = [
  { label: "Developer Program 審核通過", done: false },
  { label: "取得真實 sandbox payload 並驗證資料映射", done: false },
  { label: "完成 webhook / pull 整合契約", done: true },
  { label: "完成對應測試案例", done: false },
];

export function IntegrationSettings() {
  const { preferences, setPreference, garminActivities } = useWorkspace();

  const remaining = GARMIN_PRECONDITIONS.filter((p) => !p.done).length;

  return (
    <>
      <Card
        title="Garmin 活動同步"
        subtitle="以 feature flag GARMIN_ACTIVITY_SYNC_ENABLED 控制，屬於 Phase 1B。"
        reqTags={["REQ-GARMIN-001", "REQ-GARMIN-002"]}
        actions={
          <Badge tone={preferences.garminSyncEnabled ? "accent" : "neutral"} dot>
            {preferences.garminSyncEnabled ? "已開啟（示範）" : "flag 關閉"}
          </Badge>
        }
      >
        <div className="stack">
          <p style={{ fontSize: 13, lineHeight: 1.75 }}>
            Garmin Activity API 屬於 cloud-to-cloud 整合：需要使用者授權、裝置先同步到 Garmin
            Connect，第三方平台才拿得到活動資料。這是一個時程不完全掌握在工程團隊手上的外部依賴，
            因此 Phase 1 的核心交付（Phase 1A）完全不依賴它。
          </p>

          <div className="card" style={{ boxShadow: "none", background: "var(--surface-2)" }}>
            <div className="card-body">
              <div className="row-between" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: 13 }}>開啟 flag 的前置條件</strong>
                <span className="field-hint">還差 {remaining} 項</span>
              </div>
              <ul className="stack-sm">
                {GARMIN_PRECONDITIONS.map((item) => (
                  <li key={item.label} className="row" style={{ gap: 9 }}>
                    <span style={{ color: item.done ? "var(--good)" : "var(--text-muted)" }}>
                      <Icon name={item.done ? "check" : "x"} size={15} strokeWidth={2} />
                    </span>
                    <span
                      style={{
                        fontSize: 13,
                        color: item.done ? "var(--text)" : "var(--text-2)",
                      }}
                    >
                      {item.label}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <SwitchRow
            title="在這個示範中模擬 flag 已開啟"
            description={`打開後會把 ${garminActivities.length} 筆 garmin_epoc 來源的紀錄納入畫面，你可以看到兩種單位並存時的處理方式：不相加、分開呈現、資料品質降為 LOW。這是示範開關，不是真的 Garmin 連線。`}
            checked={preferences.garminSyncEnabled}
            onChange={(next) => setPreference("garminSyncEnabled", next)}
            reqTags={["REQ-LOAD-006"]}
          />

          {preferences.garminSyncEnabled && (
            <Notice tone="accent" icon="alert">
              注意這個 flag 在真實環境不應該只由前端切換。這裡的開關只是為了讓評審看到兩種單位並存時
              的行為差異。
            </Notice>
          )}
        </div>
      </Card>

      <Card
        title="LINE 通知"
        subtitle="每日課表提醒透過 LINE Push Message 發送。"
        reqTags={["REQ-SCHED-003"]}
      >
        <div className="stack">
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>連結狀態</div>
              <div className="field-hint">已綁定 LINE 帳號，可隨時解除。</div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <Badge tone="good" dot>
                已連結
              </Badge>
              <Button size="sm">解除連結</Button>
            </div>
          </div>

          <hr className="divider" />

          <div className="stack-sm">
            <strong style={{ fontSize: 13 }}>重複發送是怎麼被擋掉的</strong>
            <p className="field-hint" style={{ lineHeight: 1.8 }}>
              排程任務的冪等鍵是 <code className="mono">(user_id, job_type, local_date)</code>，
              用來擋掉內部重複觸發。同時，推播呼叫會帶上由這個鍵衍生的穩定{" "}
              <code className="mono">X-Line-Retry-Key</code>：即使伺服器在寫入「已發送」狀態前當機，
              重試時 LINE 平台本身也會以 409 拒絕重複送出。
            </p>
          </div>
        </div>
      </Card>

      <Card
        title="Webhook 事件處理"
        subtitle="各家 provider 的簽章、重送與順序語意不同，驗證邏輯個別實作。"
        reqTags={["REQ-WEBHOOK-PROVIDER-001", "REQ-WEBHOOK-003"]}
      >
        <div className="grid-2">
          <div className="stack-sm">
            <strong style={{ fontSize: 13 }}>一律儲存</strong>
            <ul className="field-hint" style={{ lineHeight: 1.9 }}>
              <li>provider</li>
              <li>event_id</li>
              <li>received_at</li>
              <li>body_hash</li>
              <li>status</li>
            </ul>
          </div>
          <div className="stack-sm">
            <strong style={{ fontSize: 13 }}>原始 payload</strong>
            <p className="field-hint" style={{ lineHeight: 1.8 }}>
              只在除錯或處理需要時才儲存，須加密並設定明確 TTL。生理資料的原始 payload
              不會出現在應用程式 log 或 Sentry。
            </p>
          </div>
        </div>
        <Notice tone="neutral" icon="info" >
          去重靠資料庫層的 UNIQUE (provider, event_id) 加上 INSERT ... ON CONFLICT DO
          NOTHING，不是靠應用程式自己記得。
        </Notice>
      </Card>
    </>
  );
}

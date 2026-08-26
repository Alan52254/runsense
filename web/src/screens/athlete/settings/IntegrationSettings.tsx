import { Badge, Button, Card, Notice, SwitchRow } from "../../../components/ui.tsx";
import { Icon } from "../../../components/Icon.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";
import { apiConfigured } from "../../../data/apiClient.ts";
import { useLocale } from "../../../state/LocaleContext.tsx";

/** REQ-GARMIN-002: the flag stays off until every one of these is done. */
const GARMIN_PRECONDITIONS = [
  { zh: "Developer Program 審核通過", en: "Developer Program approval completed", done: false },
  { zh: "取得真實 sandbox payload 並驗證資料映射", en: "Validate data mapping with a real sandbox payload", done: false },
  { zh: "完成 webhook / pull 整合契約", en: "Complete the webhook and pull integration contract", done: true },
  { zh: "完成對應測試案例", en: "Complete the corresponding test cases", done: false },
];

export function IntegrationSettings() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { preferences, setPreference, garminActivities, liveGarminEnabled, liveGarminReason } =
    useWorkspace();

  const remaining = GARMIN_PRECONDITIONS.filter((p) => !p.done).length;

  return (
    <>
      {apiConfigured && liveGarminReason && (
        <Notice tone={liveGarminEnabled ? "accent" : "neutral"} icon="info" title={en ? "Server flag status" : "伺服器端 flag 狀態"}>
          <code className="mono">GARMIN_ACTIVITY_SYNC_ENABLED</code>：
          {liveGarminEnabled ? (en ? "On" : "開啟") : (en ? "Off" : "關閉")} — {en
            ? liveGarminReason
            : (liveGarminEnabled ? "伺服器已開啟活動同步" : "伺服器尚未開啟活動同步")}
        </Notice>
      )}

      <Card
        title={en ? "Garmin activity sync" : "Garmin 活動同步"}
        subtitle={en ? "Available only after external review and connection testing are complete." : "完成外部服務審核與連線測試後才會開放。"}
        actions={
          <Badge tone={preferences.garminSyncEnabled ? "accent" : "neutral"} dot>
            {preferences.garminSyncEnabled ? (en ? "Testing" : "測試中") : (en ? "Not available" : "尚未開放")}
          </Badge>
        }
      >
        <div className="stack">
          <p style={{ fontSize: 13, lineHeight: 1.75 }}>
            {en
              ? "The Garmin Activity API is a cloud-to-cloud integration. Athletes must grant access and their device must first sync with Garmin Connect before a third-party platform can receive activity data. Because this external dependency has its own timeline, manual logging and training analysis do not depend on it."
              : "Garmin Activity API 屬於 cloud-to-cloud 整合：需要使用者授權、裝置先同步到 Garmin Connect，第三方平台才拿得到活動資料。這是一個時程不完全掌握在工程團隊手上的外部依賴，因此目前的手動紀錄與訓練分析不依賴這項整合。"}
          </p>

          <div className="card" style={{ boxShadow: "none", background: "var(--surface-2)" }}>
            <div className="card-body">
              <div className="row-between" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: 13 }}>{en ? "Requirements before enabling the flag" : "開啟 flag 的前置條件"}</strong>
                <span className="field-hint">{en ? `${remaining} remaining` : `還差 ${remaining} 項`}</span>
              </div>
              <ul className="stack-sm">
                {GARMIN_PRECONDITIONS.map((item) => (
                  <li key={item.zh} className="row" style={{ gap: 9 }}>
                    <span style={{ color: item.done ? "var(--good)" : "var(--text-muted)" }}>
                      <Icon name={item.done ? "check" : "x"} size={15} strokeWidth={2} />
                    </span>
                    <span
                      style={{
                        fontSize: 13,
                        color: item.done ? "var(--text)" : "var(--text-2)",
                      }}
                    >
                      {en ? item.en : item.zh}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <SwitchRow
            title={en ? "Simulate an enabled flag in this demo" : "在這個示範中模擬 flag 已開啟"}
            description={en
              ? `Enabling this includes ${garminActivities.length} garmin_epoc records so you can see how mixed units are handled: never summed, displayed separately, with data quality set to LOW. This demo switch is not a real Garmin connection.`
              : `打開後會把 ${garminActivities.length} 筆 garmin_epoc 來源的紀錄納入畫面，你可以看到兩種單位並存時的處理方式：不相加、分開呈現、資料品質降為 LOW。這是示範開關，不是真的 Garmin 連線。`}
            checked={preferences.garminSyncEnabled}
            onChange={(next) => setPreference("garminSyncEnabled", next)}
          />

          {preferences.garminSyncEnabled && (
            <Notice tone="accent" icon="alert">
              {en
                ? "In a real environment this flag must not be controlled by the frontend alone. This switch only demonstrates behavior when two units coexist."
                : "注意這個 flag 在真實環境不應該只由前端切換。這裡的開關只是為了讓評審看到兩種單位並存時的行為差異。"}
            </Notice>
          )}
        </div>
      </Card>

      <Card
        title={en ? "LINE notifications" : "LINE 通知"}
        subtitle={en ? "Daily workout reminders are sent through LINE Push Message." : "每日課表提醒透過 LINE Push Message 發送。"}
      >
        <div className="stack">
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>{en ? "Connection status" : "連結狀態"}</div>
              <div className="field-hint">{en ? "A LINE account is connected and can be disconnected at any time." : "已綁定 LINE 帳號，可隨時解除。"}</div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <Badge tone="good" dot>
                {en ? "Connected" : "已連結"}
              </Badge>
              <Button size="sm">{en ? "Disconnect" : "解除連結"}</Button>
            </div>
          </div>

          <hr className="divider" />

          <div className="stack-sm">
            <strong style={{ fontSize: 13 }}>{en ? "How duplicate delivery is prevented" : "重複發送是怎麼被擋掉的"}</strong>
            <p className="field-hint" style={{ lineHeight: 1.8 }}>
              {en ? "The scheduled job uses " : "排程任務的冪等鍵是 "}<code className="mono">(user_id, job_type, local_date)</code>{en
                ? " as its idempotency key to prevent internal duplicate triggers. Push requests also carry a stable "
                : "，用來擋掉內部重複觸發。同時，推播呼叫會帶上由這個鍵衍生的穩定 "}
              <code className="mono">X-Line-Retry-Key</code>{en
                ? ". Even if the server fails before recording delivery, LINE returns 409 for the duplicate retry."
                : "：即使伺服器在寫入「已發送」狀態前當機，重試時 LINE 平台本身也會以 409 拒絕重複送出。"}
            </p>
          </div>
        </div>
      </Card>

      <Card
        title={en ? "Webhook event handling" : "Webhook 事件處理"}
        subtitle={en ? "Each provider has different signature, retry, and ordering semantics, so validation is provider-specific." : "各家 provider 的簽章、重送與順序語意不同，驗證邏輯個別實作。"}
      >
        <div className="grid-2">
          <div className="stack-sm">
            <strong style={{ fontSize: 13 }}>{en ? "Always stored" : "一律儲存"}</strong>
            <ul className="field-hint" style={{ lineHeight: 1.9 }}>
              <li>provider</li>
              <li>event_id</li>
              <li>received_at</li>
              <li>body_hash</li>
              <li>status</li>
            </ul>
          </div>
          <div className="stack-sm">
            <strong style={{ fontSize: 13 }}>{en ? "Raw payload" : "原始 payload"}</strong>
            <p className="field-hint" style={{ lineHeight: 1.8 }}>
              {en
                ? "Stored only when required for debugging or processing, encrypted, and assigned an explicit TTL. Raw physiological payloads never appear in application logs or Sentry."
                : "只在除錯或處理需要時才儲存，須加密並設定明確 TTL。生理資料的原始 payload 不會出現在應用程式 log 或 Sentry。"}
            </p>
          </div>
        </div>
        <Notice tone="neutral" icon="info" >
          {en
            ? "Deduplication is enforced by database-level UNIQUE (provider, event_id) plus INSERT ... ON CONFLICT DO NOTHING, not application memory."
            : "去重靠資料庫層的 UNIQUE (provider, event_id) 加上 INSERT ... ON CONFLICT DO NOTHING，不是靠應用程式自己記得。"}
        </Notice>
      </Card>
    </>
  );
}

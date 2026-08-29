import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  Notice,
  SwitchRow,
} from "../../../components/ui.tsx";
import { StepUpModal } from "../../../components/domain.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";
import { useAuth } from "../../../state/AuthContext.tsx";
import { useLocale } from "../../../state/LocaleContext.tsx";

const RETENTION_ROWS = [
  { data: "Completed training records", zhData: "已完成的訓練紀錄", zhRetention: "帳號存續期間", enRetention: "Life of the account", zhBasis: "選手擁有的正典紀錄", enBasis: "Athlete-owned canonical record" },
  { data: "Daily training-load data", zhData: "每日體能負荷數據", zhRetention: "帳號存續期間", enRetention: "Life of the account", zhBasis: "由訓練紀錄衍生", enBasis: "Derived from training records" },
  { data: "Body-status self-reported notes", zhData: "身體狀況自述內容", zhRetention: "帳號存續期間，可單獨刪除", enRetention: "Life of the account; separately deletable", zhBasis: "敏感自述內容", enBasis: "Sensitive self-reported content" },
  { data: "Login & security activity log", zhData: "登入與安全事件紀錄", zhRetention: "24 個月", enRetention: "24 months", zhBasis: "安全事件追溯", enBasis: "Security event traceability" },
];

export function PrivacySettings() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { auth } = useAuth();
  const {
    preferences,
    setPreference,
    exportData,
    requestAccountDeletion,
    deletionRequest,
    lastExportAtUtc,
  } = useWorkspace();

  const [stepUpFor, setStepUpFor] = useState<null | "export" | "delete">(null);
  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";

  return (
    <>
      {deletionRequest && (
        <Notice tone="warning" icon="alert" title={en ? "Deletion request recorded" : "已登記刪除申請"}>
          {en ? "Requested at: " : "申請時間："}
          {new Intl.DateTimeFormat(locale, { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(deletionRequest.requestedAtUtc))}.
          {en ? " We've recorded your request. Deletion and de-identification are currently handled by our team rather than automatically -- you'll be notified once it's complete." : "我們已經收到你的申請。刪除與去識別化目前由專人處理，不是自動執行 —— 完成後會通知你。"}
        </Notice>
      )}

      <Card
        title={en ? "Your data rights" : "你的資料權利"}
        subtitle={en ? "You can initiate each action yourself without contacting support." : "以下每一項都可以由你自己發動，不需要透過客服。"}
      >
        <div className="stack">
          <div className="row-between" style={{ padding: "10px 0" }}>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 570 }}>{en ? "Export currently supported data" : "匯出目前支援的資料"}</div>
              <div className="field-hint" style={{ maxWidth: "62ch" }}>
                {en ? "The JSON export currently includes your time zone, city, training records, and training load. Body status is not included yet. This high-risk action requires identity verification." : "目前包含個人時區與城市、訓練紀錄及訓練負荷，以 JSON 格式下載；身體狀況尚未納入。這是高風險操作，需要再次驗證身分。"}
                {lastExportAtUtc && (
                  <> {en ? "Last exported: " : "上次匯出："}{new Intl.DateTimeFormat(locale, { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(lastExportAtUtc))}.</>
                )}
              </div>
            </div>
            <Button icon="download" onClick={() => setStepUpFor("export")}>
              {en ? "Export" : "匯出"}
            </Button>
          </div>

          <hr className="divider" />

          <div className="row-between" style={{ padding: "10px 0" }}>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 570 }}>{en ? "Correct personal data" : "更正個人資料"}</div>
              <div className="field-hint" style={{ maxWidth: "62ch" }}>
                {en ? "You can change your time zone and city on the Profile tab. To correct your name, email, or an existing training record, contact us." : "目前可在「個人資料」分頁修改時區與城市。姓名、email 或既有訓練紀錄如需更正，請聯繫我們協助處理。"}
              </div>
            </div>
            <Badge tone="neutral" dot>
              {en ? "Partially supported" : "部分支援"}
            </Badge>
          </div>

          <hr className="divider" />

          <div className="row-between" style={{ padding: "10px 0" }}>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 570 }}>{en ? "Delete account and data" : "刪除帳號與資料"}</div>
              <div className="field-hint" style={{ maxWidth: "62ch" }}>
                {en ? "You can record a deletion request here. To cancel a request, or if you have questions about legally required retention, contact us." : "你可以在這裡登記刪除需求。如需取消申請，或對依法必須保留的資料有疑問，請聯繫我們。"}
              </div>
            </div>
            <Button
              variant="danger"
              icon="trash"
              disabled={deletionRequest !== null}
              onClick={() => setStepUpFor("delete")}
            >
              {en ? "Record request" : "登記申請"}
            </Button>
          </div>
        </div>
      </Card>

      <Card
        title={en ? "Stop specific uses of your data" : "停止特定用途的資料處理"}
        subtitle={en ? "Disable one use while keeping the other features available." : "你可以只關閉其中一種用途，其餘功能照常運作。"}
      >
        <div>
          <SwitchRow
            title={en ? "Motivational tone suggestions" : "情緒／語氣建議"}
            description={en ? "When disabled, workout numbers remain unchanged. Encouraging copy is replaced with a fixed template, and this feature never changes prescription fields." : "關閉後，課表的數字完全不變，只是不再顯示鼓勵性質的文字，改用固定模板。這個功能本來就不會影響任何處方欄位。"}
            checked={preferences.llmToneEnabled}
            onChange={(next) => setPreference("llmToneEnabled", next)}
          />
          <SwitchRow
            title={en ? "Workout reminder notifications" : "訓練提醒推播"}
            description={en ? "Daily workout reminders sent through LINE. Disabling them does not affect workout generation or display." : "透過 LINE 發送的每日課表提醒。關閉不影響課表本身的產生與顯示。"}
            checked={preferences.pushNotificationsEnabled}
            onChange={(next) => setPreference("pushNotificationsEnabled", next)}
          />
        </div>
      </Card>

      <Card
        title={en ? "Data retention periods" : "資料保留期限"}
        subtitle={en ? "After the retention period expires, we delete or de-identify the data." : "保留期限到期後，我們會刪除或將資料去識別化。"}
        flush
      >
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{en ? "Data category" : "資料類別"}</th>
                <th>{en ? "Retention" : "保留期限"}</th>
                <th>{en ? "Basis" : "依據"}</th>
              </tr>
            </thead>
            <tbody>
              {RETENTION_ROWS.map((row) => (
                <tr key={row.data}>
                  <td>{en ? row.data : (row.zhData ?? row.data)}</td>
                  <td>{en ? row.enRetention : row.zhRetention}</td>
                  <td className="muted">{en ? row.enBasis : row.zhBasis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={en ? "Privacy policy version" : "隱私權政策版本"}>
        <div className="row-between">
          <div>
            <div style={{ fontSize: 13, fontWeight: 560 }}>
              {en ? "Version currently accepted" : "你目前同意的版本"}：{preferences.acceptedPolicyVersion}
            </div>
            <div className="field-hint">
              {en ? "Your acceptance record isn't synced to your account yet, so it resets each time you sign in." : "你的同意紀錄目前還沒有跟帳號同步，所以每次登入都會重設。"}
            </div>
          </div>
        </div>
      </Card>

      <StepUpModal
        open={stepUpFor !== null}
        action={stepUpFor === "export" ? (en ? "export your personal data" : "匯出個人完整資料") : (en ? "request account deletion" : "申請刪除帳號")}
        onCancel={() => setStepUpFor(null)}
        onVerified={() => {
          if (stepUpFor === "export") exportData();
          if (stepUpFor === "delete") requestAccountDeletion();
          setStepUpFor(null);
        }}
      />
    </>
  );
}

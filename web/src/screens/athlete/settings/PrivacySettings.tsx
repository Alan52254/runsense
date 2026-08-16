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
import { formatInstant } from "../../../lib/format.ts";

const RETENTION_ROWS: { data: string; retention: string; basis: string }[] = [
  { data: "completed_activities", retention: "帳號存續期間", basis: "選手擁有的正典紀錄" },
  { data: "training_load_daily", retention: "帳號存續期間", basis: "由訓練紀錄衍生" },
  { data: "injury_report_details", retention: "帳號存續期間，可單獨刪除", basis: "敏感自述內容" },
  { data: "audit_log", retention: "24 個月", basis: "安全事件追溯" },
  { data: "webhook_metadata", retention: "90 天", basis: "重送與去重判定" },
  { data: "webhook 原始 payload", retention: "7 天，加密儲存", basis: "僅除錯需要時保存" },
  { data: "訂閱與付款紀錄", retention: "5 年", basis: "稅務法規要求，刪除帳號後仍保留" },
];

export function PrivacySettings() {
  const { auth } = useAuth();
  const {
    preferences,
    setPreference,
    exportData,
    requestAccountDeletion,
    cancelAccountDeletion,
    deletionRequest,
    lastExportAtUtc,
  } = useWorkspace();

  const [stepUpFor, setStepUpFor] = useState<null | "export" | "delete">(null);
  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";

  return (
    <>
      {deletionRequest && (
        <Notice tone="critical" icon="alert" title="帳號刪除申請進行中">
          <div className="row-between" style={{ marginTop: 6 }}>
            <span>
              申請於 {formatInstant(deletionRequest.requestedAtUtc, timezone)} 受理，
              {formatInstant(deletionRequest.purgeAfterUtc, timezone)} 之後執行刪除或去識別化。
              例外：{deletionRequest.retainedForLegalReasons.join("、")}。
            </span>
            <Button size="sm" onClick={cancelAccountDeletion}>
              取消申請
            </Button>
          </div>
        </Notice>
      )}

      <Card
        title="你的資料權利"
        subtitle="以下每一項都可以由你自己發動，不需要透過客服。"
      >
        <div className="stack">
          <div className="row-between" style={{ padding: "10px 0" }}>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 570 }}>匯出完整資料</div>
              <div className="field-hint" style={{ maxWidth: "62ch" }}>
                包含所有 athlete-owned 範圍的紀錄，以 JSON 格式下載。這是高風險操作，需要再次驗證身分。
                {lastExportAtUtc && (
                  <> 上次匯出：{formatInstant(lastExportAtUtc, timezone)}。</>
                )}
              </div>
            </div>
            <Button icon="download" onClick={() => setStepUpFor("export")}>
              匯出
            </Button>
          </div>

          <hr className="divider" />

          <div className="row-between" style={{ padding: "10px 0" }}>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 570 }}>更正個人資料</div>
              <div className="field-hint" style={{ maxWidth: "62ch" }}>
                姓名、email、時區、城市都可以直接在「個人資料」分頁修改。訓練紀錄的內容可在訓練紀錄頁編輯。
              </div>
            </div>
            <Badge tone="good" dot>
              可自行操作
            </Badge>
          </div>

          <hr className="divider" />

          <div className="row-between" style={{ padding: "10px 0" }}>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 570 }}>刪除帳號與資料</div>
              <div className="field-hint" style={{ maxWidth: "62ch" }}>
                受理後有 30 天緩衝期可以取消。期滿執行刪除或去識別化，但法規要求保存的交易紀錄除外。
              </div>
            </div>
            <Button
              variant="danger"
              icon="trash"
              disabled={deletionRequest !== null}
              onClick={() => setStepUpFor("delete")}
            >
              申請刪除
            </Button>
          </div>
        </div>
      </Card>

      <Card
        title="停止特定用途的資料處理"
        subtitle="你可以只關閉其中一種用途，其餘功能照常運作。"
      >
        <div>
          <SwitchRow
            title="情緒／語氣建議"
            description="關閉後，課表的數字完全不變，只是不再顯示鼓勵性質的文字，改用固定模板。這個功能本來就不會影響任何處方欄位。"
            checked={preferences.llmToneEnabled}
            onChange={(next) => setPreference("llmToneEnabled", next)}
          />
          <SwitchRow
            title="訓練提醒推播"
            description="透過 LINE 發送的每日課表提醒。關閉不影響課表本身的產生與顯示。"
            checked={preferences.pushNotificationsEnabled}
            onChange={(next) => setPreference("pushNotificationsEnabled", next)}
          />
        </div>
      </Card>

      <Card
        title="資料保留期限"
        subtitle="各類資料的保留期限已定義，並由排程執行刪除或去識別化。"
        flush
      >
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>資料類別</th>
                <th>保留期限</th>
                <th>依據</th>
              </tr>
            </thead>
            <tbody>
              {RETENTION_ROWS.map((row) => (
                <tr key={row.data}>
                  <td className="mono">{row.data}</td>
                  <td>{row.retention}</td>
                  <td className="muted">{row.basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="隱私權政策版本">
        <div className="row-between">
          <div>
            <div style={{ fontSize: 13, fontWeight: 560 }}>
              你目前同意的版本：{preferences.acceptedPolicyVersion}
            </div>
            <div className="field-hint">
              政策與服務條款皆有版本號，系統記錄你同意的版本與時間。版本更新時會請你重新確認。
            </div>
          </div>
          <Badge tone="good" dot>
            已是最新版
          </Badge>
        </div>
      </Card>

      <Notice tone="neutral" icon="info">
        實際的法律適用與資料分類，仍須由法律專業於上線前確認。這個畫面呈現的是對應的工程實作，
        不是法律意見。
      </Notice>

      <StepUpModal
        open={stepUpFor !== null}
        action={stepUpFor === "export" ? "匯出個人完整資料" : "申請刪除帳號"}
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

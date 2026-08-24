import { useState } from "react";
import { Badge, Button, Card, Notice } from "../../../components/ui.tsx";
import { StepUpModal } from "../../../components/domain.tsx";
import { Icon } from "../../../components/Icon.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";
import { useAuth } from "../../../state/AuthContext.tsx";
import { AUDIT_LABEL, formatInstant, formatRelative } from "../../../lib/format.ts";

export function SecuritySettings() {
  const { auth } = useAuth();
  const { sessions, auditLog, revokeSession, revokeOtherSessions, appendAudit } =
    useWorkspace();

  const [stepUpFor, setStepUpFor] = useState<null | "password" | "revoke-all">(null);

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";
  const mfaSatisfied = auth?.actor.mfaSatisfied ?? false;

  return (
    <>
      <Card title="登入方式">
        <div className="stack">
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>Email 驗證</div>
              <div className="field-hint">帳號啟用前必須完成驗證。</div>
            </div>
            <Badge tone="good" dot>
              已驗證
            </Badge>
          </div>
          <hr className="divider" />
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>登入頻率限制</div>
              <div className="field-hint">
                連續失敗會逐步延長重試間隔，失敗事件寫入稽核日誌（不含密碼內容）。
              </div>
            </div>
            <Badge tone="good" dot>
              已啟用
            </Badge>
          </div>
          <hr className="divider" />
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>密碼</div>
              <div className="field-hint">變更密碼會撤銷其他所有 session。</div>
            </div>
            <Button size="sm" onClick={() => setStepUpFor("password")}>
              變更密碼
            </Button>
          </div>
        </div>
      </Card>

      <Card
        title="多因素驗證"
        subtitle="owner 與 head_coach 角色在 Phase 1 即要求 MFA 或 Passkey。"
      >
        <div className="row-between">
          <div>
            <div className="row" style={{ gap: 8 }}>
              <Badge tone={mfaSatisfied ? "good" : "warning"} dot>
                {mfaSatisfied ? "本次連線已完成 MFA" : "尚未完成 MFA"}
              </Badge>
              <span className="req-tag">目前角色：{auth?.actor.role}</span>
            </div>
            <p className="field-hint" style={{ marginTop: 6, maxWidth: "64ch" }}>
              角色在登入期間被提升為 head_coach 時，系統會立即要求補做 MFA 才能繼續操作 —— 不是等到
              下次登入。切換到教練視角就會觸發這個流程。
            </p>
          </div>
        </div>
      </Card>

      <Card
        title="Token 與儲存"
        subtitle="網頁端不把 refresh token 放進 localStorage。"
      >
        <div className="grid-2">
          <div className="stack-sm">
            <div className="row" style={{ gap: 8 }}>
              <Icon name="refresh" size={15} />
              <strong style={{ fontSize: 13 }}>Refresh token rotation</strong>
            </div>
            <p className="field-hint">
              每次使用後即失效並換發新 token。偵測到已失效的 token 被重用時，整個 token family
              會立即被撤銷。
            </p>
          </div>
          <div className="stack-sm">
            <div className="row" style={{ gap: 8 }}>
              <Icon name="lock" size={15} />
              <strong style={{ fontSize: 13 }}>儲存位置</strong>
            </div>
            <p className="field-hint">
              行動端使用 OS 安全儲存區；網頁端的存取權杖只存在記憶體中，重新整理就需要重新登入。
            </p>
          </div>
        </div>
      </Card>

      <Card
        title="有效的登入 session"
        subtitle="你可以查看並撤銷自己所有的登入。"
        actions={
          sessions.length > 1 ? (
            <Button size="sm" onClick={() => setStepUpFor("revoke-all")}>
              登出其他所有裝置
            </Button>
          ) : undefined
        }
        flush
      >
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>裝置</th>
                <th>位置</th>
                <th>IP</th>
                <th>最近活動</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.id}>
                  <td>
                    <div className="row" style={{ gap: 8 }}>
                      <span style={{ fontWeight: 560 }}>{session.device}</span>
                      {session.isCurrent && <Badge tone="accent">目前這台</Badge>}
                    </div>
                  </td>
                  <td className="muted">{session.location}</td>
                  <td className="mono">{session.ipMasked}</td>
                  <td className="muted">{formatRelative(session.lastActiveAtUtc)}</td>
                  <td style={{ textAlign: "right" }}>
                    {!session.isCurrent && (
                      <Button size="sm" onClick={() => revokeSession(session.id)}>
                        撤銷
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="帳號活動紀錄"
        subtitle="活動紀錄不會保存密碼、登入憑證或身體自述原文。"
        flush
      >
        <ul>
          {auditLog.slice(0, 8).map((entry) => (
            <li
              key={entry.id}
              style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)" }}
            >
              <div className="row-between">
                <div className="row" style={{ gap: 10 }}>
                  <Badge
                    tone={
                      entry.event === "AUTH_FAILURE" || entry.event === "CROSS_TENANT_DENIED"
                        ? "warning"
                        : entry.event === "CONSENT_REVOKE"
                          ? "serious"
                          : "neutral"
                    }
                  >
                    {AUDIT_LABEL[entry.event]}
                  </Badge>
                  <span style={{ fontSize: 13 }}>{entry.summary}</span>
                </div>
                <span className="field-hint">{formatInstant(entry.atUtc, timezone)}</span>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <StepUpModal
        open={stepUpFor !== null}
        action={stepUpFor === "password" ? "變更密碼" : "登出其他所有裝置"}
        onCancel={() => setStepUpFor(null)}
        onVerified={() => {
          if (stepUpFor === "revoke-all") revokeOtherSessions();
          if (stepUpFor === "password") appendAudit("ROLE_CHANGE", "變更密碼並撤銷其他 session");
          setStepUpFor(null);
        }}
      />

      <Notice tone="neutral" icon="shield">
        資料匯出、角色變更、帳單變更等高風險操作，即使已經登入也會要求重新驗證身分。
      </Notice>
    </>
  );
}

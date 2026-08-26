import { useState } from "react";
import { Badge, Button, Card, Notice } from "../../../components/ui.tsx";
import { StepUpModal } from "../../../components/domain.tsx";
import { Icon } from "../../../components/Icon.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";
import { useAuth } from "../../../state/AuthContext.tsx";
import { AUDIT_LABEL, formatRelative } from "../../../lib/format.ts";
import { useLocale } from "../../../state/LocaleContext.tsx";

const AUDIT_LABEL_EN: Record<string, string> = {
  AUTH_LOGIN: "Sign-in success", AUTH_FAILURE: "Sign-in failure", ROLE_CHANGE: "Role change",
  CONSENT_GRANT: "Consent granted", CONSENT_REVOKE: "Consent revoked", DATA_EXPORT: "Data export",
  CROSS_TENANT_DENIED: "Cross-team access denied", BILLING_CHANGE: "Subscription change",
};

function localizedAuditSummary(summary: string, event: string, en: boolean): string {
  if (!en) {
    if (summary === "Demo login succeeded") return "示範登入成功";
    if (summary.startsWith("Athlete exported")) return "選手已匯出自己的資料";
    if (summary.startsWith("Granted ")) return "已開啟資料分享授權";
    if (summary.startsWith("Revoked ")) return "已撤銷資料分享授權";
    return summary;
  }
  const demo: Record<string, string> = {
    "從 Chrome / Windows 登入": "Signed in from Chrome / Windows",
    "匯出個人完整資料（已完成 step-up 驗證）": "Exported personal data after step-up verification",
    "密碼錯誤（連續第 1 次）": "Incorrect password (first consecutive failure)",
    "從 RunSense App / iPhone 登入": "Signed in from RunSense App / iPhone",
  };
  return demo[summary] ?? AUDIT_LABEL_EN[event] ?? summary;
}

export function SecuritySettings() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { auth } = useAuth();
  const { sessions, auditLog, revokeSession, revokeOtherSessions, appendAudit } =
    useWorkspace();

  const [stepUpFor, setStepUpFor] = useState<null | "password" | "revoke-all">(null);

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";
  const mfaSatisfied = auth?.actor.mfaSatisfied ?? false;

  return (
    <>
      <Card title={en ? "Sign-in methods" : "登入方式"}>
        <div className="stack">
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>{en ? "Email verification" : "Email 驗證"}</div>
              <div className="field-hint">{en ? "Verification is required before the account is activated." : "帳號啟用前必須完成驗證。"}</div>
            </div>
            <Badge tone="good" dot>
              {en ? "Verified" : "已驗證"}
            </Badge>
          </div>
          <hr className="divider" />
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>{en ? "Sign-in rate limiting" : "登入頻率限制"}</div>
              <div className="field-hint">
                {en ? "Repeated failures progressively increase the retry delay. Failure events are written to the audit log without password content." : "連續失敗會逐步延長重試間隔，失敗事件寫入稽核日誌（不含密碼內容）。"}
              </div>
            </div>
            <Badge tone="good" dot>
              {en ? "Enabled" : "已啟用"}
            </Badge>
          </div>
          <hr className="divider" />
          <div className="row-between">
            <div>
              <div style={{ fontSize: 13, fontWeight: 560 }}>{en ? "Password" : "密碼"}</div>
              <div className="field-hint">{en ? "Changing your password revokes every other session." : "變更密碼會撤銷其他所有 session。"}</div>
            </div>
            <Button size="sm" onClick={() => setStepUpFor("password")}>
              {en ? "Change password" : "變更密碼"}
            </Button>
          </div>
        </div>
      </Card>

      <Card
        title={en ? "Multi-factor authentication" : "多因素驗證"}
        subtitle={en ? "Owner and head_coach roles require MFA or a passkey in Phase 1." : "owner 與 head_coach 角色在 Phase 1 即要求 MFA 或 Passkey。"}
      >
        <div className="row-between">
          <div>
            <div className="row" style={{ gap: 8 }}>
              <Badge tone={mfaSatisfied ? "good" : "warning"} dot>
                {mfaSatisfied ? (en ? "MFA complete for this session" : "本次連線已完成 MFA") : (en ? "MFA not completed" : "尚未完成 MFA")}
              </Badge>
              <span className="req-tag">{en ? "Current role" : "目前角色"}：{auth?.actor.role}</span>
            </div>
            <p className="field-hint" style={{ marginTop: 6, maxWidth: "64ch" }}>
              {en
                ? "If your role is elevated to head_coach during a session, RunSense immediately requires MFA before you can continue. Switching to coach view triggers this flow."
                : "角色在登入期間被提升為 head_coach 時，系統會立即要求補做 MFA 才能繼續操作 —— 不是等到下次登入。切換到教練視角就會觸發這個流程。"}
            </p>
          </div>
        </div>
      </Card>

      <Card
        title={en ? "Tokens and storage" : "Token 與儲存"}
        subtitle={en ? "The web app never stores refresh tokens in localStorage." : "網頁端不把 refresh token 放進 localStorage。"}
      >
        <div className="grid-2">
          <div className="stack-sm">
            <div className="row" style={{ gap: 8 }}>
              <Icon name="refresh" size={15} />
              <strong style={{ fontSize: 13 }}>Refresh token rotation</strong>
            </div>
            <p className="field-hint">
              {en ? "Each token expires when used and is replaced. Reuse of an expired token revokes the entire token family." : "每次使用後即失效並換發新 token。偵測到已失效的 token 被重用時，整個 token family 會立即被撤銷。"}
            </p>
          </div>
          <div className="stack-sm">
            <div className="row" style={{ gap: 8 }}>
              <Icon name="lock" size={15} />
              <strong style={{ fontSize: 13 }}>{en ? "Storage location" : "儲存位置"}</strong>
            </div>
            <p className="field-hint">
              {en ? "Mobile uses secure OS storage. Web access tokens exist only in memory, so a refresh requires signing in again." : "行動端使用 OS 安全儲存區；網頁端的存取權杖只存在記憶體中，重新整理就需要重新登入。"}
            </p>
          </div>
        </div>
      </Card>

      <Card
        title={en ? "Active sessions" : "有效的登入 session"}
        subtitle={en ? "Review and revoke any of your sign-ins." : "你可以查看並撤銷自己所有的登入。"}
        actions={
          sessions.length > 1 ? (
            <Button size="sm" onClick={() => setStepUpFor("revoke-all")}>
              {en ? "Sign out all other devices" : "登出其他所有裝置"}
            </Button>
          ) : undefined
        }
        flush
      >
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{en ? "Device" : "裝置"}</th>
                <th>{en ? "Location" : "位置"}</th>
                <th>IP</th>
                <th>{en ? "Recent activity" : "最近活動"}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.id}>
                  <td>
                    <div className="row" style={{ gap: 8 }}>
                      <span style={{ fontWeight: 560 }}>{session.device}</span>
                      {session.isCurrent && <Badge tone="accent">{en ? "This device" : "目前這台"}</Badge>}
                    </div>
                  </td>
                  <td className="muted">{session.location}</td>
                  <td className="mono">{session.ipMasked}</td>
                  <td className="muted">{formatRelative(session.lastActiveAtUtc, Date.now(), locale)}</td>
                  <td style={{ textAlign: "right" }}>
                    {!session.isCurrent && (
                      <Button size="sm" onClick={() => revokeSession(session.id)}>
                        {en ? "Revoke" : "撤銷"}
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
        title={en ? "Account activity" : "帳號活動紀錄"}
        subtitle={en ? "Activity records never store passwords, sign-in credentials, or private body-status notes." : "活動紀錄不會保存密碼、登入憑證或身體自述原文。"}
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
                    {en ? (AUDIT_LABEL_EN[entry.event] ?? entry.event) : AUDIT_LABEL[entry.event]}
                  </Badge>
                  <span style={{ fontSize: 13 }}>{localizedAuditSummary(entry.summary, entry.event, en)}</span>
                </div>
                <span className="field-hint">{new Intl.DateTimeFormat(locale, { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(entry.atUtc))}</span>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <StepUpModal
        open={stepUpFor !== null}
        action={stepUpFor === "password" ? (en ? "change your password" : "變更密碼") : (en ? "sign out all other devices" : "登出其他所有裝置")}
        onCancel={() => setStepUpFor(null)}
        onVerified={() => {
          if (stepUpFor === "revoke-all") revokeOtherSessions();
          if (stepUpFor === "password") appendAudit("ROLE_CHANGE", en ? "Changed password and revoked other sessions" : "變更密碼並撤銷其他 session");
          setStepUpFor(null);
        }}
      />

      <Notice tone="neutral" icon="shield">
        {en ? "High-risk actions such as data export, role changes, and billing changes require identity verification even after sign-in." : "資料匯出、角色變更、帳單變更等高風險操作，即使已經登入也會要求重新驗證身分。"}
      </Notice>
    </>
  );
}

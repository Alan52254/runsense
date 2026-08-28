import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Modal,
  Notice,
  SwitchRow,
} from "../../components/ui.tsx";
import { Avatar } from "../../components/ui.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import {
  CONSENT_DESCRIPTION,
  CONSENT_LABEL,
  formatRelative,
} from "../../lib/format.ts";
import { useAuth } from "../../state/AuthContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import type { ConsentScope } from "../../lib/types.ts";

const SCOPE_ORDER: ConsentScope[] = [
  "activity_summary",
  "training_load",
  "injury_status",
  "injury_detail",
];

const CONSENT_EN: Record<ConsentScope, { label: string; description: string }> = {
  activity_summary: { label: "Workout summaries", description: "Coach can view workout date, duration, RPE, and session load." },
  training_load: { label: "Training-load trends", description: "Coach can view 7-day and 28-day load, ratio, and data quality." },
  injury_status: { label: "Body-status summary", description: "Coach can view issue status and severity, but not your written note." },
  injury_detail: { label: "Private body-status note", description: "Coach can read your full note. This is an independent consent scope." },
};

export function TeamScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { auth } = useAuth();
  const {
    memberships,
    consents,
    setConsent,
    acceptInvitation,
    declineInvitation,
    leaveTeam,
    consentRevokedAt,
    athleteDataStatus,
    refetchAthleteData,
  } = useWorkspace();

  const [leaveTarget, setLeaveTarget] = useState<string | null>(null);

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";
  const instant = (value: string) => new Intl.DateTimeFormat(locale, {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(value));
  const invitations = memberships.filter((m) => m.status === "INVITED");
  const activeTeams = memberships.filter((m) => m.status === "ACTIVE");
  const pastTeams = memberships.filter((m) => m.status === "LEFT");

  const grantedCount = (teamId: string) =>
    consents.filter((c) => c.teamId === teamId && c.granted).length;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Team & consent" : "團隊與授權"}</h1>
          <p className="page-desc">
            {en ? "Teams never own copies of your training data. What a coach can see is decided at request time from active membership, role permissions, and your current consent scopes." : "團隊不會擁有你的訓練資料副本。教練能看到什麼，是在查詢的當下依據「有效成員關係 + 角色權限 + 授權範圍」動態決定的。"}
          </p>
        </div>
      </div>

      {consentRevokedAt && (
        <Notice tone="warning" icon="refresh" title={en ? "Consent change is taking effect" : "授權變更生效中"}>
          {en ? "This takes effect almost immediately. Anything your coach already downloaded before now, though, can't be recalled." : "這項變更幾乎立即生效。不過教練在這之前已經下載的資料，沒有辦法追回。"}
        </Notice>
      )}

      {athleteDataStatus === "loading" && memberships.length === 0 && (
        <Notice tone="neutral" icon="refresh">{en ? "Loading team and consent data…" : "正在取得團隊與授權資料…"}</Notice>
      )}
      {athleteDataStatus === "error" && (
        <Notice tone="critical" icon="alert" title={en ? "Unable to load team data" : "無法載入團隊資料"}>
          <Button size="sm" onClick={() => void refetchAthleteData()}>{en ? "Try again" : "重新嘗試"}</Button>
        </Notice>
      )}

      {invitations.length > 0 && (
        <Card
          title={en ? `${invitations.length} pending invitation${invitations.length === 1 ? "" : "s"}` : `${invitations.length} 個待處理的邀請`}
          subtitle={en ? "Joining a team always requires your approval; a coach cannot enroll you unilaterally." : "加入團隊一定要經過你的同意，教練無法單方面把你加進去。"}
          flush
        >
          <ul>
            {invitations.map((invite) => (
              <li
                key={invite.teamId}
                style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}
              >
                <div className="row-between">
                  <div className="row" style={{ gap: 12 }}>
                    <Avatar name={invite.teamName} large />
                    <div>
                      <div style={{ fontWeight: 600 }}>{invite.teamName}</div>
                      <div className="field-hint">
                        {en ? "Coach" : "教練"} {invite.coachName} · {en ? "Invited" : "邀請於"}{" "}
                        {formatRelative(invite.invitedAtUtc, Date.now(), locale)}
                      </div>
                    </div>
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <Button onClick={() => declineInvitation(invite.teamId)}>{en ? "Decline" : "婉拒"}</Button>
                    <Button variant="primary" onClick={() => acceptInvitation(invite.teamId)}>
                      {en ? "Accept" : "接受邀請"}
                    </Button>
                  </div>
                </div>
                <Notice tone="neutral" icon="info" >
                  {en ? "Accepting makes you a member only. You still choose each sharing scope independently; nothing is enabled by default." : "接受邀請只代表成為成員。你要分享哪些範圍，接受之後仍然逐項自己決定，預設不會全開。"}
                </Notice>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {activeTeams.length === 0 ? (
        <Card>
          <EmptyState
            icon="users"
            title={en ? "You have not joined a team" : "目前沒有加入任何團隊"}
            description={en ? "Your training records remain safely stored in your own account." : "你的訓練紀錄仍然完整保存在自己的帳號下，不受影響。"}
          />
        </Card>
      ) : (
        activeTeams.map((team) => (
          <Card
            key={team.teamId}
            title={team.teamName}
            subtitle={`${en ? "Coach" : "教練"} ${team.coachName} · ${en ? "Since" : "自"} ${team.joinedAtUtc ? instant(team.joinedAtUtc) : "—"}${en ? "" : " 起"}`}
            actions={
              <div className="row" style={{ gap: 8 }}>
                <Badge tone="good" dot>
                  {en ? "Active member" : "有效成員"}
                </Badge>
                <Button size="sm" onClick={() => setLeaveTarget(team.teamId)}>
                  {en ? "Leave team" : "離開團隊"}
                </Button>
              </div>
            }
          >
            <div className="stack">
              <div className="row-between">
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{en ? "Data sharing scopes" : "資料分享範圍"}</div>
                  <div className="field-hint">
                    {en ? "Each scope is independent. Turning one off does not affect the others." : "每一項都是獨立授權，關掉其中一項不影響其他項目。"}
                  </div>
                </div>
                <Badge tone={grantedCount(team.teamId) === 0 ? "neutral" : "accent"}>
                  {en ? "Enabled" : "已開啟"} {grantedCount(team.teamId)} / {SCOPE_ORDER.length}
                </Badge>
              </div>

              <div>
                {SCOPE_ORDER.map((scope) => {
                  const grant = consents.find(
                    (c) => c.teamId === team.teamId && c.scope === scope,
                  );
                  return (
                    <SwitchRow
                      key={scope}
                      title={en ? CONSENT_EN[scope].label : CONSENT_LABEL[scope]}
                      description={en ? CONSENT_EN[scope].description : CONSENT_DESCRIPTION[scope]}
                      checked={grant?.granted ?? false}
                      onChange={(next) => void setConsent(scope, next, team.teamId)}
                    />
                  );
                })}
              </div>

              <Notice tone="neutral" icon="shield" title={en ? "Sharing changes apply immediately" : "分享設定會立即套用"}>
                {en ? "Each roster request uses your current sharing settings. Disabled data is not retained in the projection." : "教練每次開啟名單時，都會依你當下的分享設定決定可見內容；關閉後不會繼續顯示舊資料。"}
              </Notice>
            </div>
          </Card>
        ))
      )}

      {pastTeams.length > 0 && (
        <Card title={en ? "Former teams" : "已離開的團隊"} flush>
          <ul>
            {pastTeams.map((team) => (
              <li
                key={team.teamId}
                style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}
              >
                <div className="row-between">
                  <div>
                    <div style={{ fontWeight: 560 }}>{team.teamName}</div>
                    <div className="field-hint">
                      {en ? "Left" : "離開於"} {team.leftAtUtc ? instant(team.leftAtUtc) : "—"}
                      · {en ? "All consent scopes revoked" : "所有授權範圍已同時撤銷"}
                    </div>
                  </div>
                  <Badge>{en ? "Left" : "已離隊"}</Badge>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title={en ? "Data ownership" : "資料歸屬"}>
        <div className="grid-2">
          <div className="stack-sm">
            <div className="row" style={{ gap: 8 }}>
              <Icon name="shield" size={15} />
              <strong style={{ fontSize: 13 }}>{en ? "Your personal training data" : "你的個人訓練資料"}</strong>
            </div>
            <ul className="field-hint" style={{ lineHeight: 1.9 }}>
              <li>{en ? "Completed workouts and training load" : "完成的訓練紀錄與訓練負荷"}</li>
              <li>{en ? "Body-status summaries and private notes" : "身體狀況摘要與自述內容"}</li>
              <li>{en ? "Running shoes and personal annotations" : "跑鞋與個人訓練註記"}</li>
            </ul>
          </div>
          <div className="stack-sm">
            <div className="row" style={{ gap: 8 }}>
              <Icon name="users" size={15} />
              <strong style={{ fontSize: 13 }}>{en ? "Team-created content" : "團隊建立的內容"}</strong>
            </div>
            <ul className="field-hint" style={{ lineHeight: 1.9 }}>
              <li>{en ? "Workout assignments and team notes" : "課表指派與團隊註記"}</li>
              <li>{en ? "Team settings and subscription data" : "團隊設定與訂閱資料"}</li>
            </ul>
            <p className="field-hint">
              {en ? "After you leave, the team may retain team-owned data such as assignment history, but it can no longer query your athlete-owned records." : "你離隊之後，團隊可以保留自己擁有的資料（例如課表指派歷史），但無法再查詢任何屬於你的紀錄。"}
            </p>
          </div>
        </div>
      </Card>

      <Modal
        open={leaveTarget !== null}
        title={en ? "Leave this team?" : "離開這個團隊？"}
        description={en ? "Your data will be removed from the coach dashboard and all consent scopes revoked. Rejoining later requires a new consent flow." : "離隊後教練儀表板會即時移除你的資料，所有授權範圍同時撤銷。日後重新加入需要重走一次同意流程，不會沿用舊的授權。"}
        onClose={() => setLeaveTarget(null)}
        footer={
          <>
            <Button onClick={() => setLeaveTarget(null)}>{en ? "Cancel" : "取消"}</Button>
            <Button
              variant="danger"
              onClick={() => {
                if (leaveTarget) leaveTeam(leaveTarget);
                setLeaveTarget(null);
              }}
            >
              {en ? "Confirm leave" : "確認離開"}
            </Button>
          </>
        }
      >
        <Notice tone="neutral" icon="info">
          {en ? "Team-owned data, including assignment history, remains with the team and is not part of your personal records." : "團隊擁有的資料（課表指派歷史等）會保留在團隊那邊，這部分不屬於你的個人紀錄。"}
        </Notice>
      </Modal>
    </>
  );
}

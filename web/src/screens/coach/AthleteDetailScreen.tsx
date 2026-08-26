import { Link, useParams } from "react-router-dom";
import {
  Avatar,
  Badge,
  Card,
  EmptyState,
  Notice,
  StatTile,
} from "../../components/ui.tsx";
import { Sparkline } from "../../components/charts.tsx";
import {
  DataQualityBadge,
  MaskedValue,
  SeverityBadge,
} from "../../components/domain.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { formatNumber } from "../../lib/format.ts";
import type { ConsentScope } from "../../lib/types.ts";
import { useLocale } from "../../state/LocaleContext.tsx";

const ALL_SCOPES: ConsentScope[] = [
  "activity_summary",
  "training_load",
  "injury_status",
  "injury_detail",
];

export function AthleteDetailScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const consentLabel: Record<ConsentScope, string> = en
    ? { activity_summary: "Training summary", training_load: "Training-load trend", injury_status: "Body-status summary", injury_detail: "Private body-status note" }
    : { activity_summary: "訓練摘要", training_load: "訓練負荷趨勢", injury_status: "身體狀況（有無不適／程度）", injury_detail: "身體狀況自述原文" };
  const { athleteId = "" } = useParams();
  const { canViewAthlete } = useAuth();
  const { coachRoster, assignments } = useWorkspace();

  const rosterIds = coachRoster.map((a) => a.athleteId);

  // REQ-RLS-006: the id in the URL is a query parameter, not a credential.
  // It only resolves if the *actor* is authorized for this roster.
  if (!canViewAthlete(athleteId, rosterIds)) {
    return (
      <Card>
        <EmptyState
          icon="lock"
          title={en ? "You do not have access to this athlete" : "沒有權限查看這位選手"}
          description={en ? "An athlete ID in the URL grants no access. Authorization follows the signed-in actor's active membership and role." : "網址列上的選手 ID 不會授予任何權限。授權判定依據的是登入者本人的有效成員關係與角色權限。"}
          action={
            <Link className="btn btn-secondary btn-sm" to="/coach">
              {en ? "Back to team overview" : "回團隊總覽"}
            </Link>
          }
        />
      </Card>
    );
  }

  const athlete = coachRoster.find((a) => a.athleteId === athleteId);
  if (!athlete) {
    return (
      <Card>
        <EmptyState icon="search" title={en ? "Athlete not found" : "找不到這位選手"} />
      </Card>
    );
  }

  const granted = (scope: ConsentScope) => athlete.grantedScopes.includes(scope);
  const athleteAssignments = assignments.filter((a) => a.athleteId === athleteId);

  return (
    <>
      <div className="page-head">
        <div className="row" style={{ gap: 14 }}>
          <Avatar name={athlete.name} large />
          <div>
            <h1 className="page-title">{athlete.name}</h1>
            <p className="page-desc">
              {en ? "Only the scopes currently shared by this athlete are shown. Consent can be revoked at any time and is checked whenever this page loads." : "只顯示這位選手目前授權的範圍。授權隨時可能被撤銷，這個畫面每次載入都重新檢查。"}
            </p>
          </div>
        </div>
        <Link className="btn btn-secondary" to="/coach">
          {en ? "Back to overview" : "回總覽"}
        </Link>
      </div>

      <Card title={en ? "Current sharing scopes" : "目前的授權範圍"}>
        <div className="grid-4">
          {ALL_SCOPES.map((scope) => (
            <div key={scope} className="stack-sm">
              <div className="row" style={{ gap: 8 }}>
                <span
                  style={{
                    color: granted(scope) ? "var(--good)" : "var(--text-muted)",
                  }}
                >
                  <Icon name={granted(scope) ? "check" : "lock"} size={15} strokeWidth={2} />
                </span>
                <strong style={{ fontSize: 13 }}>{consentLabel[scope]}</strong>
              </div>
              <span className="self-start">
                <Badge tone={granted(scope) ? "good" : "neutral"} dot>
                  {granted(scope) ? (en ? "Authorized" : "已授權") : (en ? "Not authorized" : "未授權")}
                </Badge>
              </span>
            </div>
          ))}
        </div>
      </Card>

      {granted("training_load") ? (
        <>
          <div className="grid-4">
            <Card>
              <StatTile
                label={en ? "7-day load" : "7 天負荷"}
                value={formatNumber(athlete.acuteLoadAu ?? 0)}
                unit="AU"
              />
            </Card>
            <Card>
              <StatTile
                label={en ? "28-day weekly equivalent" : "28 天週等效"}
                value={formatNumber(athlete.chronicLoadAu ?? 0)}
                unit="AU"
              />
            </Card>
            <Card>
              <StatTile
                label={en ? "Acute-to-chronic load ratio" : "短長期負荷比"}
                value={athlete.loadRatio === null ? (en ? "Not calculated" : "不計算") : athlete.loadRatio.toFixed(2)}
                foot={athlete.loadRatio === null ? (en ? "Data-quality threshold not met" : "資料品質未達門檻") : (en ? "No traffic-light classification" : "沒有對應的燈號")}
              />
            </Card>
            <Card>
              <StatTile
                label={en ? "Data quality" : "資料品質"}
                small
                value={<DataQualityBadge quality={athlete.dataQuality} />}
              />
            </Card>
          </div>

          {athlete.last14DaysLoad.length > 0 && (
            <Card title={en ? "Last 14 days of load" : "近 14 天負荷"} subtitle={en ? "Unit: AU. Device load is not combined." : "單位 AU，不與裝置負荷混算。"}>
              <Sparkline values={athlete.last14DaysLoad} width={640} height={72} />
            </Card>
          )}
        </>
      ) : (
        <Card title={en ? "Training load" : "訓練負荷"}>
          <EmptyState
            icon="lock"
            title={en ? "This athlete has not shared training load" : "這位選手沒有授權訓練負荷"}
            description={en ? "Without consent, no values are displayed, including approximate ranges or team-average comparisons." : "沒有授權時，這裡不顯示任何數字 —— 包含「大概的區間」或「和團隊平均的比較」。"}
          />
        </Card>
      )}

      <div className="grid-2">
        <Card title={en ? "Body-status summary" : "身體狀況摘要"}>
          {granted("injury_status") ? (
            <div className="stack-sm">
              <div className="row-between">
                <span className="muted">{en ? "Current issue" : "目前是否有不適"}</span>
                <strong>{athlete.injuryHasIssue ? (en ? "Yes" : "有") : (en ? "No" : "沒有")}</strong>
              </div>
              <div className="row-between">
                <span className="muted">{en ? "Severity" : "程度分級"}</span>
                {athlete.injurySeverityBand ? (
                  <SeverityBadge band={athlete.injurySeverityBand} />
                ) : (
                  <span className="dim">—</span>
                )}
              </div>
              <p className="field-hint">
                {en ? "This section shows only the body-status summary the athlete agreed to share." : "此區只顯示選手同意分享的身體狀況摘要。"}
              </p>
            </div>
          ) : (
            <div className="stack-sm">
              <span className="self-start">
                <MaskedValue scopeLabel={consentLabel.injury_status} />
              </span>
              <p className="field-hint">{en ? "This athlete has not shared their body-status summary." : "這位選手沒有授權身體狀況摘要。"}</p>
            </div>
          )}
        </Card>

        <Card title={en ? "Athlete's private note" : "選手自述原文"}>
          {granted("injury_detail") ? (
            <div className="stack-sm">
              {athlete.injuryFreeText ? (
                <>
                  <p style={{ fontSize: 13, lineHeight: 1.8 }}>「{athlete.injuryFreeText}」</p>
                  <p className="field-hint">
                    {en ? "Private notes use separate consent from the body-status summary and receive stricter access protection." : "自述內容與身體狀況摘要分開授權，並受到較嚴格的存取保護。"}
                  </p>
                </>
              ) : (
                <p className="field-hint">{en ? "This athlete did not enter a private note." : "這位選手沒有填寫自述內容。"}</p>
              )}
            </div>
          ) : (
            <div className="stack-sm">
              <span className="self-start">
                <MaskedValue scopeLabel={consentLabel.injury_detail} />
              </span>
              <p className="field-hint">
                {en ? "Even when the summary is shared, the original note requires separate consent. It is not an attachment to the summary." : "即使上面的摘要已授權，自述原文仍需要獨立授權才會顯示 —— 它不是摘要的附屬項目。"}
              </p>
            </div>
          )}
        </Card>
      </div>

      <Card
        title={en ? "Assignment history" : "課表指派紀錄"}
        subtitle={en ? "Team-created workout assignments are retained for continuity." : "由團隊建立的課表紀錄會保留，方便持續追蹤訓練安排。"}
        flush
      >
        {athleteAssignments.length === 0 ? (
          <EmptyState icon="assignment" title={en ? "No assignments yet" : "還沒有指派紀錄"} />
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{en ? "Date" : "日期"}</th>
                  <th>{en ? "Workout" : "內容"}</th>
                  <th className="num">{en ? "Duration" : "時長"}</th>
                  <th>{en ? "Intensity" : "強度"}</th>
                  <th>{en ? "Status" : "狀態"}</th>
                </tr>
              </thead>
              <tbody>
                {athleteAssignments.map((assignment) => (
                  <tr key={assignment.id}>
                    <td>{assignment.localDate}</td>
                    <td style={{ fontWeight: 550 }}>{assignment.title}</td>
                    <td className="num">{assignment.durationMinutes} {en ? "min" : "分"}</td>
                    <td className="muted">{assignment.intensityLabel}</td>
                    <td>
                      <Badge
                        tone={
                          assignment.status === "COMPLETED"
                            ? "good"
                            : assignment.status === "MISSED"
                              ? "warning"
                              : "neutral"
                        }
                        dot
                      >
                        {assignment.status === "COMPLETED"
                          ? (en ? "Completed" : "已完成")
                          : assignment.status === "MISSED"
                            ? (en ? "Missed" : "未完成")
                            : (en ? "Scheduled" : "已排定")}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Notice tone="neutral" icon="shield">
        {en ? "To verify access controls, replace the athlete ID in the URL with one outside this team. The page rejects access and records a CROSS_TENANT_DENIED audit event." : "想確認授權真的有效？把網址列的選手 ID 換成一個不屬於這個團隊的值，畫面會直接拒絕，並在稽核日誌留下 CROSS_TENANT_DENIED 事件。"}
      </Notice>
    </>
  );
}

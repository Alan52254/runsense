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
import { CONSENT_LABEL, formatNumber } from "../../lib/format.ts";
import type { ConsentScope } from "../../lib/types.ts";

const ALL_SCOPES: ConsentScope[] = [
  "activity_summary",
  "training_load",
  "injury_status",
  "injury_detail",
];

export function AthleteDetailScreen() {
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
          title="沒有權限查看這位選手"
          description="網址列上的選手 ID 不會授予任何權限。授權判定依據的是登入者本人的有效成員關係與角色權限。"
          action={
            <Link className="btn btn-secondary btn-sm" to="/coach">
              回團隊總覽
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
        <EmptyState icon="search" title="找不到這位選手" />
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
              只顯示這位選手目前授權的範圍。授權隨時可能被撤銷，這個畫面每次載入都重新檢查。
            </p>
          </div>
        </div>
        <Link className="btn btn-secondary" to="/coach">
          回總覽
        </Link>
      </div>

      <Card title="目前的授權範圍">
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
                <strong style={{ fontSize: 13 }}>{CONSENT_LABEL[scope]}</strong>
              </div>
              <span className="self-start">
                <Badge tone={granted(scope) ? "good" : "neutral"} dot>
                  {granted(scope) ? "已授權" : "未授權"}
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
                label="7 天負荷"
                value={formatNumber(athlete.acuteLoadAu ?? 0)}
                unit="AU"
              />
            </Card>
            <Card>
              <StatTile
                label="28 天週等效"
                value={formatNumber(athlete.chronicLoadAu ?? 0)}
                unit="AU"
              />
            </Card>
            <Card>
              <StatTile
                label="load_ratio"
                value={athlete.loadRatio === null ? "不計算" : athlete.loadRatio.toFixed(2)}
                foot={athlete.loadRatio === null ? "資料品質未達門檻" : "沒有對應的燈號"}
              />
            </Card>
            <Card>
              <StatTile
                label="資料品質"
                small
                value={<DataQualityBadge quality={athlete.dataQuality} />}
              />
            </Card>
          </div>

          {athlete.last14DaysLoad.length > 0 && (
            <Card title="近 14 天負荷" subtitle="單位 AU，不與裝置負荷混算。">
              <Sparkline values={athlete.last14DaysLoad} width={640} height={72} />
            </Card>
          )}
        </>
      ) : (
        <Card title="訓練負荷">
          <EmptyState
            icon="lock"
            title="這位選手沒有授權訓練負荷"
            description="沒有授權時，這裡不顯示任何數字 —— 包含「大概的區間」或「和團隊平均的比較」。"
          />
        </Card>
      )}

      <div className="grid-2">
        <Card title="身體狀況摘要">
          {granted("injury_status") ? (
            <div className="stack-sm">
              <div className="row-between">
                <span className="muted">目前是否有不適</span>
                <strong>{athlete.injuryHasIssue ? "有" : "沒有"}</strong>
              </div>
              <div className="row-between">
                <span className="muted">程度分級</span>
                {athlete.injurySeverityBand ? (
                  <SeverityBadge band={athlete.injurySeverityBand} />
                ) : (
                  <span className="dim">—</span>
                )}
              </div>
              <p className="field-hint">
                這些欄位來自 injury_reports 表，對應 injury_status 授權範圍。
              </p>
            </div>
          ) : (
            <div className="stack-sm">
              <span className="self-start">
                <MaskedValue scopeLabel={CONSENT_LABEL.injury_status} />
              </span>
              <p className="field-hint">這位選手沒有授權身體狀況摘要。</p>
            </div>
          )}
        </Card>

        <Card title="選手自述原文">
          {granted("injury_detail") ? (
            <div className="stack-sm">
              {athlete.injuryFreeText ? (
                <>
                  <p style={{ fontSize: 13, lineHeight: 1.8 }}>「{athlete.injuryFreeText}」</p>
                  <p className="field-hint">
                    來自 injury_report_details 表。這段內容不會出現在稽核日誌或錯誤追蹤系統。
                  </p>
                </>
              ) : (
                <p className="field-hint">這位選手沒有填寫自述內容。</p>
              )}
            </div>
          ) : (
            <div className="stack-sm">
              <span className="self-start">
                <MaskedValue scopeLabel={CONSENT_LABEL.injury_detail} />
              </span>
              <p className="field-hint">
                即使上面的摘要已授權，自述原文仍需要獨立授權才會顯示 —— 它不是摘要的附屬項目。
              </p>
            </div>
          )}
        </Card>
      </div>

      <Card
        title="課表指派紀錄"
        subtitle="assigned_workouts 屬於 team-owned，不受選手授權範圍影響。"
        flush
      >
        {athleteAssignments.length === 0 ? (
          <EmptyState icon="assignment" title="還沒有指派紀錄" />
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>內容</th>
                  <th className="num">時長</th>
                  <th>強度</th>
                  <th>狀態</th>
                </tr>
              </thead>
              <tbody>
                {athleteAssignments.map((assignment) => (
                  <tr key={assignment.id}>
                    <td>{assignment.localDate}</td>
                    <td style={{ fontWeight: 550 }}>{assignment.title}</td>
                    <td className="num">{assignment.durationMinutes} 分</td>
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
                          ? "已完成"
                          : assignment.status === "MISSED"
                            ? "未完成"
                            : "已排定"}
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
        想確認授權真的有效？把網址列的選手 ID 換成一個不屬於這個團隊的值，畫面會直接拒絕，
        並在稽核日誌留下 CROSS_TENANT_DENIED 事件。
      </Notice>
    </>
  );
}

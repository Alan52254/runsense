import { useNavigate } from "react-router-dom";
import { Badge, Card, Notice, StatTile } from "../../components/ui.tsx";
import { Avatar } from "../../components/ui.tsx";
import { Sparkline } from "../../components/charts.tsx";
import {
  DataQualityBadge,
  MaskedValue,
  SeverityBadge,
} from "../../components/domain.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth, COACH_IDENTITY } from "../../state/AuthContext.tsx";
import { CONSENT_LABEL, formatNumber, formatRelative } from "../../lib/format.ts";
import { DEMO_TEAM_NAME } from "../../data/demoData.ts";

export function TeamOverviewScreen() {
  const navigate = useNavigate();
  const { auth } = useAuth();
  const { coachRoster, departedNotice, consentRevokedAt } = useWorkspace();

  const withLoad = coachRoster.filter((a) => a.grantedScopes.includes("training_load"));
  const withInjury = coachRoster.filter((a) => a.grantedScopes.includes("injury_status"));
  const flagged = coachRoster.filter((a) => a.injuryHasIssue === true);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{DEMO_TEAM_NAME}</h1>
          <p className="page-desc">
            這個列表是查詢當下的投影（team_athlete_projection），不是選手資料的副本。
            每一格內容都在讀取快取之前先做過授權與同意檢查。
          </p>
        </div>
      </div>

      <Notice tone="accent" icon="shield" title="操作者身分（actor）與查詢目標是兩件事">
        目前的安全 context 是{" "}
        <code className="mono">
          app.actor_user_id = {auth?.actor.userId ?? COACH_IDENTITY.userId}
        </code>
        ，也就是登入者本人。網址列上的選手 ID 只是查詢參數，永遠不會被當成授權依據 —— 換掉它並不會
        讓你看到不該看的資料。
      </Notice>

      {consentRevokedAt && (
        <Notice tone="warning" icon="refresh">
          偵測到授權變更，投影快取正在失效中（≤5 秒）。
        </Notice>
      )}

      <div className="grid-4">
        <Card>
          <StatTile label="有效成員" value={`${coachRoster.length}`} unit="人" />
        </Card>
        <Card>
          <StatTile
            label="已授權訓練負荷"
            value={`${withLoad.length}`}
            unit={`/ ${coachRoster.length}`}
            foot="未授權者不顯示任何負荷數字"
          />
        </Card>
        <Card>
          <StatTile
            label="已授權身體狀況"
            value={`${withInjury.length}`}
            unit={`/ ${coachRoster.length}`}
            foot="摘要與自述原文是兩個獨立授權"
          />
        </Card>
        <Card>
          <StatTile
            label="回報有不適"
            value={`${flagged.length}`}
            unit="人"
            foot="僅計入已授權的選手"
          />
        </Card>
      </div>

      <Card
        title="選手狀態"
        subtitle="未授權的欄位顯示為「未授權」，而不是空白 —— 空白會被誤讀成「沒有資料」。"
        flush
      >
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>選手</th>
                <th>最近訓練</th>
                <th className="num">7 天負荷</th>
                <th className="num">28 天週等效</th>
                <th className="num">比值</th>
                <th>近 14 天</th>
                <th>資料品質</th>
                <th>身體狀況</th>
              </tr>
            </thead>
            <tbody>
              {coachRoster.map((athlete) => {
                const loadGranted = athlete.grantedScopes.includes("training_load");
                const injuryGranted = athlete.grantedScopes.includes("injury_status");
                const summaryGranted = athlete.grantedScopes.includes("activity_summary");

                return (
                  <tr
                    key={athlete.athleteId}
                    className="is-clickable"
                    onClick={() => navigate(`/coach/athletes/${athlete.athleteId}`)}
                  >
                    <td>
                      <div className="row" style={{ gap: 10 }}>
                        <Avatar name={athlete.name} />
                        <div>
                          <div style={{ fontWeight: 570 }}>{athlete.name}</div>
                          <div className="field-hint">
                            {athlete.grantedScopes.length} / 4 項授權
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="muted">
                      {summaryGranted ? (
                        (athlete.lastActivityLocalDate ?? "—")
                      ) : (
                        <MaskedValue scopeLabel={CONSENT_LABEL.activity_summary} />
                      )}
                    </td>
                    <td className="num">
                      {loadGranted ? (
                        formatNumber(athlete.acuteLoadAu ?? 0)
                      ) : (
                        <MaskedValue scopeLabel={CONSENT_LABEL.training_load} />
                      )}
                    </td>
                    <td className="num">
                      {loadGranted ? formatNumber(athlete.chronicLoadAu ?? 0) : "—"}
                    </td>
                    <td className="num">
                      {!loadGranted
                        ? "—"
                        : athlete.loadRatio === null
                          ? "不計算"
                          : athlete.loadRatio.toFixed(2)}
                    </td>
                    <td>
                      {loadGranted && athlete.last14DaysLoad.length > 0 ? (
                        <Sparkline values={athlete.last14DaysLoad} />
                      ) : (
                        <span className="dim">—</span>
                      )}
                    </td>
                    <td>
                      {loadGranted ? (
                        <DataQualityBadge quality={athlete.dataQuality} />
                      ) : (
                        <span className="dim">—</span>
                      )}
                    </td>
                    <td>
                      {injuryGranted ? (
                        athlete.injurySeverityBand ? (
                          <SeverityBadge band={athlete.injurySeverityBand} />
                        ) : (
                          <span className="dim">—</span>
                        )
                      ) : (
                        <MaskedValue scopeLabel={CONSENT_LABEL.injury_status} />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid-2">
        <Card title="近期異動">
          <div className="stack-sm">
            <div className="row-between">
              <div className="row" style={{ gap: 10 }}>
                <Avatar name={departedNotice.name} />
                <div>
                  <div style={{ fontWeight: 560 }}>{departedNotice.name}</div>
                  <div className="field-hint">
                    {formatRelative(departedNotice.leftAtUtc)}離開團隊
                  </div>
                </div>
              </div>
              <Badge>已離隊</Badge>
            </div>
            <p className="field-hint">
              離隊當下就從這份名單移除，之後無法再查詢其任何 athlete-owned 資料。
              團隊自己擁有的課表指派歷史仍然保留。重新加入必須重走同意流程，不會沿用舊授權。
            </p>
          </div>
        </Card>

        <Card title="為什麼有些格子是「未授權」">
          <div className="stack-sm">
            <p style={{ fontSize: 13, lineHeight: 1.75 }}>
              授權是 scope 化的：一位選手可以只分享訓練摘要，不分享負荷趨勢；也可以分享「有無不適」，
              但不分享自述原文。這兩者存在不同的資料表，各自套用獨立政策。
            </p>
            <p className="field-hint">
              顯示「未授權」而不是空白，是為了避免教練把「沒有權限看到」誤讀成「選手沒有這筆資料」。
            </p>
          </div>
        </Card>
      </div>
    </>
  );
}

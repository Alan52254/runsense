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
import { apiConfigured } from "../../data/apiClient.ts";
import { CONSENT_LABEL, formatNumber, formatRelative } from "../../lib/format.ts";
import { DEMO_TEAM_NAME } from "../../data/demoData.ts";

export function TeamOverviewScreen() {
  const navigate = useNavigate();
  const { coachRoster, departedNotice, consentRevokedAt, liveTeamName, rosterStatus } =
    useWorkspace();
  const teamName = apiConfigured ? (liveTeamName ?? "尚未指派團隊") : DEMO_TEAM_NAME;

  const withLoad = coachRoster.filter((a) => a.grantedScopes.includes("training_load"));
  const withInjury = coachRoster.filter((a) => a.grantedScopes.includes("injury_status"));
  const flagged = coachRoster.filter((a) => a.injuryHasIssue === true);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{teamName}</h1>
          <p className="page-desc">
            名單會依每位選手目前的分享設定更新；未分享的內容不會顯示。
          </p>
        </div>
      </div>

      {apiConfigured && rosterStatus === "error" && (
        <Notice tone="critical" icon="alert" title="無法載入團隊名單">
          請確認網路連線後重試。
        </Notice>
      )}

      {apiConfigured && rosterStatus === "loading" && coachRoster.length === 0 && (
        <Notice tone="neutral" icon="info">
          正在向伺服器取得團隊名單…
        </Notice>
      )}

      {consentRevokedAt && (
        <Notice tone="warning" icon="refresh">
          選手已更新分享設定，名單內容正在重新整理。
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
              選手離隊後會立即從名單移除，過去的課表指派紀錄仍保留。
              若重新加入，需要再次確認資料分享範圍。
            </p>
          </div>
        </Card>

        <Card title="為什麼有些格子是「未授權」">
          <div className="stack-sm">
            <p style={{ fontSize: 13, lineHeight: 1.75 }}>
              每位選手可以分別分享訓練摘要、負荷趨勢、身體狀況與自述內容。
              分享身體狀況不代表同時分享自述原文。
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

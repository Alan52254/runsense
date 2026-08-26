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
import { formatNumber, formatRelative } from "../../lib/format.ts";
import { DEMO_TEAM_NAME } from "../../data/demoData.ts";
import { useLocale } from "../../state/LocaleContext.tsx";

export function TeamOverviewScreen() {
  const { locale, t } = useLocale();
  const en = locale === "en";
  const navigate = useNavigate();
  const { coachRoster, departedNotice, consentRevokedAt, liveTeamName, rosterStatus } =
    useWorkspace();
  const teamName = apiConfigured
    ? (liveTeamName ?? (en ? "No team assigned" : "尚未指派團隊"))
    : (en ? t("teamName") : DEMO_TEAM_NAME);
  const consentLabel = {
    activity_summary: en ? "Training summary" : "訓練摘要",
    training_load: en ? "Training-load trend" : "訓練負荷趨勢",
    injury_status: en ? "Body-status summary" : "身體狀況（有無不適／程度）",
  } as const;

  const withLoad = coachRoster.filter((a) => a.grantedScopes.includes("training_load"));
  const withInjury = coachRoster.filter((a) => a.grantedScopes.includes("injury_status"));
  const flagged = coachRoster.filter((a) => a.injuryHasIssue === true);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{teamName}</h1>
          <p className="page-desc">
            {en ? "The roster follows each athlete's current sharing settings. Data they do not share is not displayed." : "名單會依每位選手目前的分享設定更新；未分享的內容不會顯示。"}
          </p>
        </div>
      </div>

      {apiConfigured && rosterStatus === "error" && (
        <Notice tone="critical" icon="alert" title={en ? "Unable to load team roster" : "無法載入團隊名單"}>
          {en ? "Check your connection and try again." : "請確認網路連線後重試。"}
        </Notice>
      )}

      {apiConfigured && rosterStatus === "loading" && coachRoster.length === 0 && (
        <Notice tone="neutral" icon="info">
          {en ? "Loading the team roster from the server…" : "正在向伺服器取得團隊名單…"}
        </Notice>
      )}

      {consentRevokedAt && (
        <Notice tone="warning" icon="refresh">
          {en ? "An athlete updated their sharing settings. The roster is refreshing." : "選手已更新分享設定，名單內容正在重新整理。"}
        </Notice>
      )}

      <div className="grid-4">
        <Card>
          <StatTile label={en ? "Active members" : "有效成員"} value={`${coachRoster.length}`} unit={en ? "athletes" : "人"} />
        </Card>
        <Card>
          <StatTile
            label={en ? "Sharing training load" : "已授權訓練負荷"}
            value={`${withLoad.length}`}
            unit={`/ ${coachRoster.length}`}
            foot={en ? "No load values are shown without consent" : "未授權者不顯示任何負荷數字"}
          />
        </Card>
        <Card>
          <StatTile
            label={en ? "Sharing body status" : "已授權身體狀況"}
            value={`${withInjury.length}`}
            unit={`/ ${coachRoster.length}`}
            foot={en ? "Summary and private notes use separate consent" : "摘要與自述原文是兩個獨立授權"}
          />
        </Card>
        <Card>
          <StatTile
            label={en ? "Reported an issue" : "回報有不適"}
            value={`${flagged.length}`}
            unit={en ? "athletes" : "人"}
            foot={en ? "Counts only athletes who shared this status" : "僅計入已授權的選手"}
          />
        </Card>
      </div>

      <Card
        title={en ? "Athlete status" : "選手狀態"}
        subtitle={en ? "Fields without consent say “Not authorized” instead of appearing blank, which could be misread as no data." : "未授權的欄位顯示為「未授權」，而不是空白 —— 空白會被誤讀成「沒有資料」。"}
        flush
      >
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{en ? "Athlete" : "選手"}</th>
                <th>{en ? "Last workout" : "最近訓練"}</th>
                <th className="num">{en ? "7-day load" : "7 天負荷"}</th>
                <th className="num">{en ? "28-day weekly equivalent" : "28 天週等效"}</th>
                <th className="num">{en ? "Ratio" : "比值"}</th>
                <th>{en ? "Last 14 days" : "近 14 天"}</th>
                <th>{en ? "Data quality" : "資料品質"}</th>
                <th>{en ? "Body status" : "身體狀況"}</th>
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
                            {en ? `${athlete.grantedScopes.length} / 4 scopes shared` : `${athlete.grantedScopes.length} / 4 項授權`}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="muted">
                      {summaryGranted ? (
                        (athlete.lastActivityLocalDate ?? "—")
                      ) : (
                        <MaskedValue scopeLabel={consentLabel.activity_summary} />
                      )}
                    </td>
                    <td className="num">
                      {loadGranted ? (
                        formatNumber(athlete.acuteLoadAu ?? 0)
                      ) : (
                        <MaskedValue scopeLabel={consentLabel.training_load} />
                      )}
                    </td>
                    <td className="num">
                      {loadGranted ? formatNumber(athlete.chronicLoadAu ?? 0) : "—"}
                    </td>
                    <td className="num">
                      {!loadGranted
                        ? "—"
                        : athlete.loadRatio === null
                          ? (en ? "Not calculated" : "不計算")
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
                        <MaskedValue scopeLabel={consentLabel.injury_status} />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className={apiConfigured ? undefined : "grid-2"}>
        {/* departedNotice is a fixed illustrative example with no backend
            behind it -- there is no roster-departure endpoint (see
            assignments.py: a departed athlete is indistinguishable from one
            who was never a member, by design, so the server can't even
            answer "who recently left"). Showing it against a live team
            would misrepresent it as this coach's actual roster history, so
            it's demo-mode only. */}
        {!apiConfigured && (
          <Card title={en ? "Recent changes" : "近期異動"}>
            <div className="stack-sm">
              <div className="row-between">
                <div className="row" style={{ gap: 10 }}>
                  <Avatar name={departedNotice.name} />
                  <div>
                    <div style={{ fontWeight: 560 }}>{departedNotice.name}</div>
                    <div className="field-hint">
                      {en ? `${formatRelative(departedNotice.leftAtUtc, Date.now(), locale)} · left the team` : `${formatRelative(departedNotice.leftAtUtc, Date.now(), locale)}離開團隊`}
                    </div>
                  </div>
                </div>
                <Badge>{en ? "Left team" : "已離隊"}</Badge>
              </div>
              <p className="field-hint">
                {en ? "Athletes are removed from the roster immediately after leaving. Previous assignments remain, and rejoining requires new sharing choices." : "選手離隊後會立即從名單移除，過去的課表指派紀錄仍保留。若重新加入，需要再次確認資料分享範圍。"}
              </p>
              <p className="field-hint" style={{ fontStyle: "italic" }}>
                {en ? "Illustrative example -- not this team's actual history." : "此為示意範例，非本團隊實際異動紀錄。"}
              </p>
            </div>
          </Card>
        )}

        <Card title={en ? "Why some cells say “Not authorized”" : "為什麼有些格子是「未授權」"}>
          <div className="stack-sm">
            <p style={{ fontSize: 13, lineHeight: 1.75 }}>
              {en ? "Each athlete can separately share training summaries, load trends, body status, and private notes. Sharing body status does not also share the original note." : "每位選手可以分別分享訓練摘要、負荷趨勢、身體狀況與自述內容。分享身體狀況不代表同時分享自述原文。"}
            </p>
            <p className="field-hint">
              {en ? "The explicit label prevents a coach from confusing missing permission with missing athlete data." : "顯示「未授權」而不是空白，是為了避免教練把「沒有權限看到」誤讀成「選手沒有這筆資料」。"}
            </p>
          </div>
        </Card>
      </div>
    </>
  );
}

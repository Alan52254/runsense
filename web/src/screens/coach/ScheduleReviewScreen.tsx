/* 團隊課表審核: every athlete's suggested week at a glance.
 *
 * Read-only across the team; the review itself happens on the athlete's
 * draft card in their one-to-one chat room, which "開啟" opens. Three coach
 * pages answer three questions: 團隊總覽 -- who needs attention now; this
 * page -- what the system suggests changing; 課表排程 -- what was actually
 * scheduled. */

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, EmptyState, Notice } from "../../components/ui.tsx";
import type { Tone } from "../../components/ui.tsx";
import { ApiError, createScheduleDraft, getDependencies, getTeamScheduleReview } from "../../data/apiClient.ts";
import type { DependencyCheck, TeamReviewRow } from "../../data/apiClient.ts";
import { useAuth } from "../../state/AuthContext.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";

/** AppShell listens for this and opens the team chat on the room. */
export function openChatRoom(roomId: string) {
  window.dispatchEvent(new CustomEvent("runsense:open-chat", { detail: { roomId } }));
}

const STATUS: Record<TeamReviewRow["status"], { text: string; tone: Tone }> = {
  not_built: { text: "未建立", tone: "neutral" },
  pending: { text: "待審核", tone: "warning" },
  edited: { text: "已修改，待發布", tone: "warning" },
  stale: { text: "草案已失效", tone: "critical" },
  published: { text: "已發布", tone: "good" },
  recorded: { text: "已記錄（回溯）", tone: "good" },
  dismissed: { text: "已作廢", tone: "neutral" },
};

const OUTCOME_LABEL: [string, string][] = [
  ["accepted", "接受"], ["edited", "修改"], ["removed", "移除"], ["coach_authored", "教練新增"],
  ["insufficient_data", "資料不足"],
];

const SEVERITY: Record<string, string> = { MILD: "輕微", MODERATE: "中等", SEVERE: "嚴重" };

const DEPENDENCY_LABEL: Record<string, string> = {
  database: "資料庫", groq: "聊天室 AI", gemini: "健康教練 AI", weather_forecast: "天氣預報",
};

function loadText(ratio: number | null): { text: string; tone: Tone } {
  if (ratio === null) return { text: "—", tone: "neutral" };
  if (ratio >= 1.5) return { text: `${ratio.toFixed(2)} 偏高`, tone: "critical" };
  if (ratio >= 1.3) return { text: `${ratio.toFixed(2)} 上升`, tone: "warning" };
  if (ratio < 0.8) return { text: `${ratio.toFixed(2)} 偏低`, tone: "neutral" };
  return { text: `${ratio.toFixed(2)} 穩定`, tone: "good" };
}

function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function ScheduleReviewScreen() {
  const { auth } = useAuth();
  const { liveTeamId } = useWorkspace();
  const token = auth?.accessToken ?? null;
  const [rows, setRows] = useState<TeamReviewRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [start, setStart] = useState(localToday());
  const [building, setBuilding] = useState<string | null>(null);
  const [deps, setDeps] = useState<Record<string, DependencyCheck> | null>(null);

  const load = useCallback(async () => {
    if (!token || !liveTeamId) return;
    try {
      setRows((await getTeamScheduleReview(token, liveTeamId)).athletes);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "無法載入團隊課表審核");
    }
  }, [token, liveTeamId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    getDependencies().then((r) => setDeps(r.checks)).catch(() => setDeps(null));
  }, []);

  const retrospective = start < localToday();

  const build = async (row: TeamReviewRow) => {
    if (!token) return;
    setBuilding(row.athlete_id);
    setError(null);
    try {
      await createScheduleDraft(token, row.room_id, retrospective ? start : undefined);
      await load();
      openChatRoom(row.room_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "建議課表產生失敗");
    } finally {
      setBuilding(null);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">團隊課表審核</h1>
          <p className="page-desc">
            系統把每位選手的負荷、身體回報、天氣與健康教練對話整理成一週建議；你審核、微調後才會排給選手。
          </p>
        </div>
      </div>

      {deps && (
        <div className="review-deps" aria-label="服務狀態">
          {Object.entries(deps).map(([k, c]) => (
            <span key={k} className={`review-dep${c.ok ? " is-ok" : c.required ? " is-down" : " is-degraded"}`}
              title={c.ok ? `${c.ms} ms` : c.without ?? c.detail ?? ""}>
              {c.ok ? "●" : "○"} {DEPENDENCY_LABEL[k] ?? k}{!c.ok && c.without ? `：${c.without}` : ""}
            </span>
          ))}
        </div>
      )}

      {error && <Notice tone="critical" icon="alert">{error}</Notice>}

      <Card
        title="這週的建議"
        subtitle={retrospective ? "回溯審核：只用開始日之前的資料產生草案，只記錄審核結果，不會排入" : "從今天起七天"}
        actions={
          <label className="review-start">
            草案開始日
            <input type="date" className="input input-sm" value={start} max={localToday()}
              onChange={(e) => setStart(e.target.value || localToday())} />
          </label>
        }
      >
        {rows === null ? (
          <div className="field-hint">載入中…</div>
        ) : rows.length === 0 ? (
          <EmptyState icon="users" title="隊上還沒有選手" />
        ) : (
          <div className="table-scroll">
            <table className="review-table">
              <thead>
                <tr>
                  <th>選手</th>
                  <th>資料完整度</th>
                  <th>建議變動</th>
                  <th>負荷</th>
                  <th>身體回報</th>
                  <th>天候影響</th>
                  <th>審核狀態</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const load = loadText(r.load_ratio);
                  const st = STATUS[r.status];
                  const d = r.draft;
                  return (
                    <tr key={r.athlete_id} className={r.status === "stale" ? "is-stale" : undefined}>
                      <td><strong>{r.name}</strong></td>
                      <td>
                        {!r.shares_load ? <span className="field-hint">未授權</span>
                          : r.observation_days === null ? "—"
                          : <span className={r.observation_days < 21 ? "dev-slow" : undefined}>{r.observation_days}/28 天</span>}
                      </td>
                      <td>
                        {d ? (
                          <>
                            {d.changes} 天{d.adjust > 0 && <span className="dev-slow">（{d.adjust} 天改輕）</span>}
                            {d.open > 0 && <div className="field-hint">{d.open} 天資料不足，留給教練</div>}
                          </>
                        ) : "—"}
                      </td>
                      <td>{r.shares_load ? <Badge tone={load.tone}>{load.text}</Badge> : <span className="field-hint">未授權</span>}</td>
                      <td>
                        {!r.shares_body ? <span className="field-hint">未授權</span>
                          : r.body_report ? (
                            <span>{r.body_report.date.slice(5).replace("-", "/")} {r.body_report.body_part ?? ""}
                              {SEVERITY[r.body_report.severity_band] ?? ""}</span>
                          ) : <span className="field-hint">無</span>}
                      </td>
                      <td>
                        {d ? (
                          <>
                            {d.hot_days > 0 ? <span className="dev-slow">{d.hot_days} 天放慢</span> : "無"}
                            <div className="field-hint">
                              {d.weather_source === "forecast" ? "預報" : d.weather_source === "climate_estimate" ? "氣候估計" : d.weather_source === "observation" ? "即時" : ""}
                            </div>
                          </>
                        ) : "—"}
                      </td>
                      <td>
                        <Badge tone={st.tone}>{st.text}</Badge>
                        {d && <div className="field-hint">第 {d.version} 版{d.review_only ? "・回溯" : ""}</div>}
                        {d?.outcomes && Object.keys(d.outcomes).length > 0 && (
                          <div className="field-hint">
                            {OUTCOME_LABEL.filter(([k]) => d.outcomes![k]).map(([k, label]) => `${label} ${d.outcomes![k]}`).join("・")}
                          </div>
                        )}
                      </td>
                      <td className="review-actions">
                        {d && r.status !== "not_built" && r.status !== "dismissed" && (
                          <Button size="sm" variant="ghost" onClick={() => openChatRoom(r.room_id)}>開啟</Button>
                        )}
                        <Button size="sm" variant={d ? "secondary" : "primary"} disabled={building !== null}
                          onClick={() => void build(r)}>
                          {building === r.athlete_id ? "整理中…" : d && r.status !== "published" && r.status !== "recorded" ? "重新產生" : "產生草案"}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

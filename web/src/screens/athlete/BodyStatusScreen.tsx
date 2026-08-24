import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Notice,
  Segmented,
} from "../../components/ui.tsx";
import { SeverityBadge } from "../../components/domain.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { formatLocalDate, SEVERITY_LABEL } from "../../lib/format.ts";
import type { SeverityBand } from "../../lib/types.ts";

const BODY_PARTS = [
  "右小腿",
  "左小腿",
  "右膝",
  "左膝",
  "右足底",
  "左足底",
  "阿基里斯腱",
  "髖／臀",
  "下背",
  "其他",
];

export function BodyStatusScreen() {
  const { today, injuryReports, injuryDetails, consents, addInjuryReport, memberships } =
    useWorkspace();

  const [hasIssue, setHasIssue] = useState<"yes" | "no">("yes");
  const [localDate, setLocalDate] = useState(today);
  const [severity, setSeverity] = useState<SeverityBand>("MILD");
  const [bodyPart, setBodyPart] = useState(BODY_PARTS[0]);
  const [freeText, setFreeText] = useState("");
  const [clientMutationId, setClientMutationId] = useState(() => crypto.randomUUID());
  const [saving, setSaving] = useState(false);

  const statusGranted = consents.find((c) => c.scope === "injury_status")?.granted ?? false;
  const detailGranted = consents.find((c) => c.scope === "injury_detail")?.granted ?? false;
  const activeTeam = memberships.find((m) => m.status === "ACTIVE");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    const saved = await addInjuryReport({
      clientMutationId,
      localDate,
      hasIssue: hasIssue === "yes",
      severityBand: severity,
      bodyPart,
      freeText,
    });
    setSaving(false);
    if (!saved) return;
    setFreeText("");
    setHasIssue("yes");
    setSeverity("MILD");
    setClientMutationId(crypto.randomUUID());
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">身體狀況</h1>
          <p className="page-desc">
            「有沒有不適／程度」與「你寫的文字內容」存在兩張不同的資料表，各自套用獨立的授權政策。
            教練拿到摘要，不代表就能讀到原文。
          </p>
        </div>
      </div>

      <div className="dashboard-split">
        <div className="stack">
          <Card title="回報身體狀況" subtitle={formatLocalDate(localDate)}>
            <form className="stack" onSubmit={submit}>
              <Field label="回報日期" htmlFor="body-status-date">
                <input
                  id="body-status-date"
                  className="input"
                  type="date"
                  max={today}
                  value={localDate}
                  onChange={(event) => {
                    setLocalDate(event.target.value);
                    setClientMutationId(crypto.randomUUID());
                  }}
                  required
                />
              </Field>
              <Field label="今天有沒有不適？">
                <Segmented
                  value={hasIssue}
                  onChange={(next) => {
                    setHasIssue(next);
                    setClientMutationId(crypto.randomUUID());
                  }}
                  options={[
                    { value: "yes", label: "有不適" },
                    { value: "no", label: "沒有不適" },
                  ]}
                />
              </Field>

              {hasIssue === "yes" && (
                <>
                  <Field label="程度分級 severity_band" htmlFor="severity">
                    <select
                      id="severity"
                      className="input"
                      value={severity}
                      onChange={(e) => {
                        setSeverity(e.target.value as SeverityBand);
                        setClientMutationId(crypto.randomUUID());
                      }}
                    >
                      {(["MILD", "MODERATE", "SEVERE"] as const).map((band) => (
                        <option key={band} value={band}>
                          {SEVERITY_LABEL[band]}（{band}）
                        </option>
                      ))}
                    </select>
                  </Field>

                  <Field label="部位" htmlFor="body-part">
                    <select
                      id="body-part"
                      className="input"
                      value={bodyPart}
                      onChange={(e) => {
                        setBodyPart(e.target.value);
                        setClientMutationId(crypto.randomUUID());
                      }}
                    >
                      {BODY_PARTS.map((part) => (
                        <option key={part}>{part}</option>
                      ))}
                    </select>
                  </Field>
                </>
              )}

              <Field
                label="自述內容"
                htmlFor="free-text"
                labelAside={
                  detailGranted ? (
                    <Badge tone="warning" dot>
                      目前已授權教練閱讀
                    </Badge>
                  ) : (
                    <Badge tone="good" dot>
                      目前只有你看得到
                    </Badge>
                  )
                }
                hint="這段文字存放在 injury_report_details，對應 injury_detail 授權範圍。"
              >
                <textarea
                  id="free-text"
                  className="input"
                  placeholder="例如：下樓梯時右小腿內側會緊，走路不痛。"
                  value={freeText}
                  onChange={(e) => {
                    setFreeText(e.target.value);
                    setClientMutationId(crypto.randomUUID());
                  }}
                />
              </Field>

              <div className="row-between">
                <span className="field-hint">
                  <Icon name="lock" size={13} /> 自述原文不會寫入稽核日誌或錯誤追蹤系統。
                </span>
                <Button type="submit" variant="primary" disabled={saving}>
                  {saving ? "儲存中…" : "送出回報"}
                </Button>
              </div>
            </form>
          </Card>

          <Card title="回報紀錄" flush>
            {injuryReports.length === 0 ? (
              <EmptyState icon="heart" title="還沒有回報紀錄" />
            ) : (
              <ul>
                {injuryReports.map((report) => {
                  const detail = injuryDetails.find((d) => d.injuryReportId === report.id);
                  return (
                    <li
                      key={report.id}
                      style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}
                    >
                      <div className="row-between" style={{ marginBottom: 6 }}>
                        <div className="row" style={{ gap: 10 }}>
                          <strong style={{ fontSize: 13 }}>
                            {formatLocalDate(report.localDate)}
                          </strong>
                          <SeverityBadge band={report.severityBand} />
                          {report.bodyPart && <Badge>{report.bodyPart}</Badge>}
                        </div>
                      </div>
                      {detail ? (
                        <p style={{ fontSize: 13, lineHeight: 1.7, color: "var(--text-2)" }}>
                          {detail.freeText}
                        </p>
                      ) : (
                        <p className="field-hint">（沒有填寫自述內容）</p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>

        <div className="stack">
          <Card title="教練現在看得到什麼">
            <div className="stack-sm">
              <div className="row-between" style={{ padding: "8px 0" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 560 }}>有無不適 / 程度分級</div>
                  <div className="field-hint">身體狀況摘要</div>
                </div>
                <Badge tone={statusGranted ? "warning" : "good"} dot>
                  {statusGranted ? "已授權" : "未授權"}
                </Badge>
              </div>
              <hr className="divider" />
              <div className="row-between" style={{ padding: "8px 0" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 560 }}>自述原文</div>
                  <div className="field-hint">個人自述內容</div>
                </div>
                <Badge tone={detailGranted ? "warning" : "good"} dot>
                  {detailGranted ? "已授權" : "未授權"}
                </Badge>
              </div>

              <Notice tone="neutral" icon="info" title="為什麼分開授權">
                你可以只分享「是否不適」與程度，不分享較私密的自述內容；兩個開關彼此獨立。
              </Notice>

              <Link className="btn btn-secondary btn-block" to="/app/team">
                調整分享範圍
              </Link>
            </div>
          </Card>

          {activeTeam && (
            <Card title="目前的團隊">
              <dl className="kv-list">
                <dt>團隊</dt>
                <dd>{activeTeam.teamName}</dd>
                <dt>教練</dt>
                <dd>{activeTeam.coachName}</dd>
              </dl>
              <p className="field-hint" style={{ marginTop: 10 }}>
                撤銷授權後，教練儀表板的快取會在 5 秒內失效，API 查詢則是下一個請求就被拒絕。
              </p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

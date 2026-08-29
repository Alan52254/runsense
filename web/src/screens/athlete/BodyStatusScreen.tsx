import { useState } from "react";
import { FirstAidKit } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  InfoTip,
  Notice,
  Segmented,
} from "../../components/ui.tsx";
import { SeverityBadge } from "../../components/domain.tsx";
import { CoachChatModal } from "../../components/CoachChatModal.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import { formatLocalDate, SEVERITY_LABEL } from "../../lib/format.ts";
import type { SeverityBand } from "../../lib/types.ts";
import type { InjuryGuidanceWireResponse } from "../../data/apiClient.ts";

const HEALTH_COACH_DISCLAIMER: Record<"zh-TW" | "en", string> = {
  "zh-TW":
    "健康教練內容僅供一般資訊與自我照護參考，不能取代醫師或其他合格醫療專業人員的診斷與治療。若有持續、嚴重或緊急症狀，請立即尋求專業協助。",
  en:
    "Health-coach content is general educational and self-care information, not a substitute for diagnosis or treatment by a qualified clinician. Seek professional help for persistent, severe, or emergency symptoms.",
};

const URGENCY_TONE: Record<InjuryGuidanceWireResponse["urgency"], "critical" | "warning" | "good"> = {
  EMERGENCY: "critical",
  PROMPT_CLINICIAN: "warning",
  SELF_CARE_NEXT_STEP: "good",
};

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

const BODY_PART_EN: Record<string, string> = {
  "右小腿": "Right calf", "左小腿": "Left calf", "右膝": "Right knee", "左膝": "Left knee",
  "右足底": "Right sole", "左足底": "Left sole", "阿基里斯腱": "Achilles tendon",
  "髖／臀": "Hip / glute", "下背": "Lower back", "其他": "Other",
};

export function BodyStatusScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const dateLabel = (value: string) => en
    ? new Intl.DateTimeFormat("en", { month: "short", day: "numeric", weekday: "short", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`))
    : formatLocalDate(value);
  const {
    today,
    injuryReports,
    injuryDetails,
    consents,
    addInjuryReport,
    requestInjuryGuidance,
    memberships,
  } = useWorkspace();

  const [hasIssue, setHasIssue] = useState<"yes" | "no">("yes");
  const [localDate, setLocalDate] = useState(today);
  const [severity, setSeverity] = useState<SeverityBand>("MILD");
  const [bodyPart, setBodyPart] = useState(BODY_PARTS[0]);
  const [freeText, setFreeText] = useState("");
  const [clientMutationId, setClientMutationId] = useState(() => crypto.randomUUID());
  const [saving, setSaving] = useState(false);
  const [chestFlag, setChestFlag] = useState(false);
  const [heatFlag, setHeatFlag] = useState(false);
  const [boneFlag, setBoneFlag] = useState(false);
  const [guidance, setGuidance] = useState<InjuryGuidanceWireResponse | null>(null);
  const [guidanceLoading, setGuidanceLoading] = useState(false);
  const [coachDrawerOpen, setCoachDrawerOpen] = useState(false);

  const statusGranted = consents.find((c) => c.scope === "injury_status")?.granted ?? false;
  const detailGranted = consents.find((c) => c.scope === "injury_detail")?.granted ?? false;
  const activeTeam = memberships.find((m) => m.status === "ACTIVE");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    const savedId = await addInjuryReport({
      clientMutationId,
      localDate,
      hasIssue: hasIssue === "yes",
      severityBand: severity,
      bodyPart,
      freeText,
    });
    if (!savedId) {
      setSaving(false);
      return;
    }
    if (hasIssue === "yes") {
      setGuidanceLoading(true);
      const result = await requestInjuryGuidance(savedId, {
        chestPainOrBreathingDifficulty: chestFlag,
        collapseConfusionOrExtremeHeatIllness: heatFlag,
        localizedBonePainWorseWithWeightBearing: boneFlag,
      });
      setGuidance(result);
      setGuidanceLoading(false);
      setCoachDrawerOpen(true);
    } else {
      setGuidance(null);
    }
    setSaving(false);
    setFreeText("");
    setHasIssue("yes");
    setSeverity("MILD");
    setChestFlag(false);
    setHeatFlag(false);
    setBoneFlag(false);
    setClientMutationId(crypto.randomUUID());
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Body status" : "身體狀況"}</h1>
          <p className="page-desc">
            {en
              ? "Issue status and severity are stored separately from your written note, with independent consent policies. Sharing the summary does not share the note."
              : "「有沒有不適／程度」與「你寫的文字內容」分開儲存，各自套用獨立的授權政策。教練拿到摘要，不代表就能讀到原文。"}
          </p>
        </div>
      </div>

      <div className="dashboard-split">
        <div className="stack">
          <Card title={en ? "Report body status" : "回報身體狀況"} subtitle={dateLabel(localDate)}>
            <form className="stack" onSubmit={submit}>
              <Field label={en ? "Report date" : "回報日期"} htmlFor="body-status-date">
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
              <Field label={en ? "Any discomfort on this date?" : "今天有沒有不適？"}>
                <Segmented
                  value={hasIssue}
                  onChange={(next) => {
                    setHasIssue(next);
                    setClientMutationId(crypto.randomUUID());
                  }}
                  options={[
                    { value: "yes", label: en ? "Yes" : "有不適" },
                    { value: "no", label: en ? "No" : "沒有不適" },
                  ]}
                />
              </Field>

              {hasIssue === "yes" && (
                <>
                  <Field label={en ? "Severity" : "程度分級"} htmlFor="severity">
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
                          {en ? ({ MILD: "Mild", MODERATE: "Moderate", SEVERE: "Severe" } as const)[band] : SEVERITY_LABEL[band]} ({band})
                        </option>
                      ))}
                    </select>
                  </Field>

                  <Field label={en ? "Body part" : "部位"} htmlFor="body-part">
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
                        <option key={part} value={part}>{en ? BODY_PART_EN[part] : part}</option>
                      ))}
                    </select>
                  </Field>

                  <Field
                    label={en
                      ? "Clear situations that need immediate triage (check any that apply)"
                      : "需要立即分流的明確狀況（請依實際情況勾選）"}
                  >
                    <div className="stack-sm">
                      {([
                        [chestFlag, setChestFlag, en ? "Chest pain or difficulty breathing" : "胸痛或呼吸困難"],
                        [heatFlag, setHeatFlag, en ? "Collapse, confusion, or severe heat-illness signs during exercise" : "運動中倒下、意識混亂或嚴重熱傷害症狀"],
                        [boneFlag, setBoneFlag, en ? "Localized bone pain that worsens with weight-bearing" : "局部骨頭疼痛且負重時更痛"],
                      ] as const).map(([checked, setter, label]) => (
                        <label key={label} className="row" style={{ gap: 8, alignItems: "flex-start", fontSize: 13 }}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => setter(e.target.checked)}
                          />
                          <span>{label}</span>
                        </label>
                      ))}
                    </div>
                  </Field>
                </>
              )}

              <Field
                label={
                  <span className="row" style={{ gap: 4 }}>
                    {en ? "Private note" : "自述內容"}
                    <InfoTip
                      text={en
                        ? "Shared separately from the summary above -- your coach needs your explicit consent to read this note."
                        : "這段文字跟上面的摘要是分開授權的，教練需要你另外同意，才能讀到這段自述原文。"}
                    />
                  </span>
                }
                htmlFor="free-text"
                labelAside={
                  detailGranted ? (
                    <Badge tone="warning" dot>
                      {en ? "Shared with coach" : "目前已授權教練閱讀"}
                    </Badge>
                  ) : (
                    <Badge tone="good" dot>
                      {en ? "Only you can view this" : "目前只有你看得到"}
                    </Badge>
                  )
                }
              >
                <textarea
                  id="free-text"
                  className="input"
                  placeholder={en ? "Example: My right calf feels tight on stairs, but walking is pain-free." : "例如：下樓梯時右小腿內側會緊，走路不痛。"}
                  value={freeText}
                  onChange={(e) => {
                    setFreeText(e.target.value);
                    setClientMutationId(crypto.randomUUID());
                  }}
                />
              </Field>

              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <Button type="submit" variant="primary" disabled={saving}>
                  {saving ? (en ? "Saving…" : "儲存中…") : (en ? "Submit report" : "送出回報")}
                </Button>
              </div>
            </form>
          </Card>

          {/* Health-coach channel (health-guidance). A fixed safety triage runs
              first; cited educational copy is attached only after. Live-backend
              only -- demo mode has no guidance provider. */}
          <Card title={en ? "Health coach" : "健康教練"}>
            {guidanceLoading ? (
              <Notice tone="neutral" icon="info">
                {en ? "Checking your report…" : "正在判讀你的回報…"}
              </Notice>
            ) : guidance ? (
              <div className="stack-sm">
                <div className="row" style={{ gap: 8, alignItems: "center" }}>
                  <Badge tone={URGENCY_TONE[guidance.urgency]} dot>
                    {guidance.urgency}
                  </Badge>
                  <Badge tone={guidance.running_allowed ? "good" : "critical"}>
                    {guidance.running_allowed
                      ? (en ? "Running allowed" : "可跑步")
                      : (en ? "Do not run" : "先不要跑")}
                  </Badge>
                </div>
                <strong style={{ fontSize: 14, lineHeight: 1.6 }}>{guidance.summary}</strong>
                {guidance.next_steps.length > 0 && (
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.7 }}>
                    {guidance.next_steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ul>
                )}
                {guidance.citations.map((citation) => (
                  <div key={citation.evidence_id} className="field-hint" style={{ fontSize: 11.5 }}>
                    {en ? "Source: " : "來源："}{citation.publisher} — {citation.title}
                    <br />
                    <a href={citation.source_url} target="_blank" rel="noreferrer">
                      {citation.source_url}
                    </a>
                  </div>
                ))}
                <span className="field-hint" style={{ fontSize: 11.5 }}>{guidance.disclaimer}</span>
                <span className="field-hint" style={{ fontSize: 10.5, color: "var(--text-3)" }}>
                  {guidance.provider_name} · {guidance.rule_version}
                  {guidance.used_fallback ? (en ? " · fallback" : "（備援）") : ""}
                </span>

                <button
                  type="button"
                  className="btn btn-sm"
                  style={{
                    backgroundColor: "var(--accent)",
                    borderColor: "var(--accent)",
                    color: "var(--accent-on)",
                    fontWeight: 700,
                    marginTop: 10,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 6,
                    padding: "10px 14px",
                    borderRadius: 10,
                    cursor: "pointer",
                  }}
                  onClick={() => setCoachDrawerOpen(true)}
                >
                  <FirstAidKit size={18} aria-hidden="true" />
                  <span>{en ? "Consult AI Coach about this report" : "向 AI 健康教練深入諮詢（帶入此傷痛報告）"}</span>
                </button>
              </div>
            ) : (
              <span className="field-hint" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
                {HEALTH_COACH_DISCLAIMER[en ? "en" : "zh-TW"]}
                {" "}
                {en
                  ? "Submit a report with discomfort to get a fixed safety triage plus cited guidance."
                  : "送出一筆有不適的回報後，系統會先做固定安全分流，再顯示有來源的衛教資訊。"}
              </span>
            )}
          </Card>

          <CoachChatModal
            isOpen={coachDrawerOpen}
            onClose={() => setCoachDrawerOpen(false)}
            reportContext={guidance ? {
              bodyPart,
              severityBand: severity,
              guidanceSummary: guidance.summary,
              nextSteps: guidance.next_steps,
            } : undefined}
          />

          <Card title={en ? "Report history" : "回報紀錄"} flush>
            {injuryReports.length === 0 ? (
              <EmptyState icon="heart" title={en ? "No reports yet" : "還沒有回報紀錄"} />
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
                            {dateLabel(report.localDate)}
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
                        <p className="field-hint">{en ? "(No private note)" : "（沒有填寫自述內容）"}</p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>

        <div className="stack">
          <Card title={en ? "What your coach can see" : "教練現在看得到什麼"}>
            <div className="stack-sm">
              <div className="row-between" style={{ padding: "8px 0" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 560 }}>{en ? "Issue status / severity" : "有無不適 / 程度分級"}</div>
                  <div className="field-hint">{en ? "Body-status summary" : "身體狀況摘要"}</div>
                </div>
                <Badge tone={statusGranted ? "warning" : "good"} dot>
                  {statusGranted ? (en ? "Shared" : "已授權") : (en ? "Not shared" : "未授權")}
                </Badge>
              </div>
              <hr className="divider" />
              <div className="row-between" style={{ padding: "8px 0" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 560 }}>{en ? "Private note" : "自述原文"}</div>
                  <div className="field-hint">{en ? "Your written note" : "個人自述內容"}</div>
                </div>
                <Badge tone={detailGranted ? "warning" : "good"} dot>
                  {detailGranted ? (en ? "Shared" : "已授權") : (en ? "Not shared" : "未授權")}
                </Badge>
              </div>

              <Notice tone="neutral" icon="info" title={en ? "Why consent is separate" : "為什麼分開授權"}>
                {en ? "You can share issue status and severity without sharing your more private note. The two controls are independent." : "你可以只分享「是否不適」與程度，不分享較私密的自述內容；兩個開關彼此獨立。"}
              </Notice>

              <Link className="btn btn-secondary btn-block" to="/app/team">
                {en ? "Manage sharing" : "調整分享範圍"}
              </Link>
            </div>
          </Card>

          {activeTeam && (
            <Card title={en ? "Current team" : "目前的團隊"}>
              <dl className="kv-list">
                <dt>{en ? "Team" : "團隊"}</dt>
                <dd>{activeTeam.teamName}</dd>
                <dt>{en ? "Coach" : "教練"}</dt>
                <dd>{activeTeam.coachName}</dd>
              </dl>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

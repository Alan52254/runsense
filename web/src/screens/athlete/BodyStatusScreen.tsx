import { Surface } from "../../components/Surface.tsx";
import { useState } from "react";
import { FirstAidKit } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Badge, Button, EmptyState, Field, Notice, Segmented } from "../../components/ui.tsx";
import { GlassPanel } from "../../components/motion.tsx";
import "../../styles/athlete.css";
import "../../styles/body.css";
import { SeverityBadge } from "../../components/domain.tsx";
import { useCoachChat } from "../../state/CoachChatContext.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import { formatLocalDate, SEVERITY_LABEL } from "../../lib/format.ts";
import type { SeverityBand } from "../../lib/types.ts";
import type { InjuryGuidanceWireResponse } from "../../data/apiClient.ts";
import { randomUUID } from "../../lib/secureContext.ts";
import { Row, Stack } from "../../components/Layout.tsx";
import { Text } from "../../components/Text.tsx";

type Locale = "zh-TW" | "en";

const HEALTH_COACH_DISCLAIMER: Record<Locale, string> = {
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

const URGENCY_LABEL: Record<InjuryGuidanceWireResponse["urgency"], Record<Locale, string>> = {
  EMERGENCY: { "zh-TW": "立即就醫", en: "Seek care now" },
  PROMPT_CLINICIAN: { "zh-TW": "盡快看醫師", en: "See a clinician soon" },
  SELF_CARE_NEXT_STEP: { "zh-TW": "可自我照護", en: "Self-care" },
};

const SEVERITY_BANDS = ["MILD", "MODERATE", "SEVERE"] as const;
const SEVERITY_EN: Record<(typeof SEVERITY_BANDS)[number], string> = { MILD: "Mild", MODERATE: "Moderate", SEVERE: "Severe" };

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

/** The side column shows the latest few reports. */
const HISTORY_SHOWN = 6;

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

  // Nothing is preselected: a report says only what the runner answered.
  const [hasIssue, setHasIssue] = useState<"yes" | "no" | null>(null);
  const [localDate, setLocalDate] = useState(today);
  const [severityChoice, setSeverity] = useState<SeverityBand | null>(null);
  const [bodyPartChoice, setBodyPart] = useState<string | null>(null);
  // The wire still carries a band and a part when there is no discomfort,
  // as it always has; those defaults never show as a selection.
  const severity: SeverityBand = severityChoice ?? "MILD";
  const bodyPart = bodyPartChoice ?? BODY_PARTS[0];
  const answered = hasIssue === "no" || (hasIssue === "yes" && severityChoice !== null && bodyPartChoice !== null);
  const missingHint = hasIssue === null
    ? (en ? "Answer whether you have any discomfort first" : "請先回答今天有沒有不適")
    : bodyPartChoice === null
      ? (en ? "Choose where it hurts" : "請選擇不適部位")
      : (en ? "Choose how bad it is" : "請選擇嚴重程度");
  const [freeText, setFreeText] = useState("");
  const [clientMutationId, setClientMutationId] = useState(() => randomUUID());
  const [saving, setSaving] = useState(false);
  const [chestFlag, setChestFlag] = useState(false);
  const [heatFlag, setHeatFlag] = useState(false);
  const [boneFlag, setBoneFlag] = useState(false);
  const [guidance, setGuidance] = useState<InjuryGuidanceWireResponse | null>(null);
  const [guidanceLoading, setGuidanceLoading] = useState(false);
  // the shared health-coach conversation
  const { openCoach } = useCoachChat();
  const reportContextOf = (result: InjuryGuidanceWireResponse) => ({
    bodyPart,
    severityBand: severity,
    guidanceSummary: result.summary,
    nextSteps: result.next_steps,
  });

  const statusGranted = consents.find((c) => c.scope === "injury_status")?.granted ?? false;
  const detailGranted = consents.find((c) => c.scope === "injury_detail")?.granted ?? false;
  const activeTeam = memberships.find((m) => m.status === "ACTIVE");

  // Any edit makes this a new report rather than a retry of the last one.
  const touch = () => setClientMutationId(randomUUID());

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!answered) return;
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
      openCoach(result ? reportContextOf(result) : undefined);
    } else {
      setGuidance(null);
    }
    setSaving(false);
    setFreeText("");
    setHasIssue(null);
    setSeverity(null);
    setBodyPart(null);
    setChestFlag(false);
    setHeatFlag(false);
    setBoneFlag(false);
    setClientMutationId(randomUUID());
  }

  const urgencyTone = guidance ? URGENCY_TONE[guidance.urgency] : "good";

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">{en ? "Body report" : "身體回報"}</h1>
      </div>

      <div className="body-layout">
        <GlassPanel as="section" padding="lg" className="body-form" aria-labelledby="body-question">
          <form className="body-form-flow" onSubmit={submit}>
            <Stack gap={3}>
              <Row justify="between" align="end" gap={4} wrap>
                <h2 className="body-question" id="body-question">
                  {en ? "Any discomfort today?" : "今天有沒有不適？"}
                </h2>
                <label className="body-date">
                  <span>{en ? "Date" : "回報日期"}</span>
                  <input
                    id="body-status-date"
                    className="input input-sm"
                    type="date"
                    max={today}
                    value={localDate}
                    onChange={(event) => {
                      setLocalDate(event.target.value);
                      touch();
                    }}
                    required
                  />
                </label>
              </Row>
              <div className="body-answer" role="group" aria-labelledby="body-question">
                <Segmented
                  value={hasIssue}
                  onChange={(next) => {
                    setHasIssue(next);
                    touch();
                  }}
                  options={[
                    { value: "yes", label: en ? "Yes" : "有不適" },
                    { value: "no", label: en ? "No" : "沒有不適" },
                  ]}
                />
              </div>
            </Stack>

            {hasIssue === "yes" && (
              <>
                <fieldset className="body-fieldset">
                  <legend className="body-legend">{en ? "Where?" : "哪個部位？"}</legend>
                  <div className="body-chips">
                    {BODY_PARTS.map((part) => (
                      <button
                        key={part}
                        type="button"
                        className="body-chip"
                        aria-pressed={bodyPartChoice === part}
                        onClick={() => {
                          setBodyPart(part);
                          touch();
                        }}
                      >
                        {en ? BODY_PART_EN[part] : part}
                      </button>
                    ))}
                  </div>
                </fieldset>

                <div className="body-fieldset">
                  <span className="body-legend" id="body-severity-label">{en ? "How bad?" : "有多嚴重？"}</span>
                  <div className="body-answer" role="group" aria-labelledby="body-severity-label">
                    <Segmented
                      value={severityChoice}
                      onChange={(next) => {
                        setSeverity(next);
                        touch();
                      }}
                      options={SEVERITY_BANDS.map((band) => ({
                        value: band,
                        label: en ? SEVERITY_EN[band] : SEVERITY_LABEL[band],
                      }))}
                    />
                  </div>
                </div>

                <fieldset className="body-fieldset">
                  <legend className="body-legend">
                    {en ? "Any of these? Check all that apply" : "有沒有以下狀況？有就勾選"}
                  </legend>
                  <Stack gap={2}>
                    {([
                      [chestFlag, setChestFlag, en ? "Chest pain or difficulty breathing" : "胸痛或呼吸困難"],
                      [heatFlag, setHeatFlag, en ? "Collapse, confusion, or severe heat-illness signs during exercise" : "運動中倒下、意識混亂或嚴重熱傷害症狀"],
                      [boneFlag, setBoneFlag, en ? "Localized bone pain that worsens with weight-bearing" : "局部骨頭疼痛且負重時更痛"],
                    ] as const).map(([checked, setter, label]) => (
                      <Row as="label" key={label} gap={3} className="body-flag">
                        <input type="checkbox" checked={checked} onChange={(e) => setter(e.target.checked)} />
                        <span>{label}</span>
                      </Row>
                    ))}
                  </Stack>
                </fieldset>
              </>
            )}

            <Field
              label={en ? "Note (optional)" : "補充說明（選填）"}
              htmlFor="free-text"
              labelAside={
                detailGranted ? (
                  <Badge tone="warning" dot>{en ? "Coach can read" : "教練可讀"}</Badge>
                ) : (
                  <Badge tone="good" dot>{en ? "Only you" : "只有你看得到"}</Badge>
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
                  touch();
                }}
              />
            </Field>

            <Stack gap={3}>
              <Row justify="end" gap={3} wrap>
                {!answered && <Text variant="caption" as="span" id="body-submit-hint">{missingHint}</Text>}
                <Button type="submit" variant="primary" disabled={saving || !answered} aria-describedby={answered ? undefined : "body-submit-hint"}>
                  {saving ? (en ? "Saving…" : "儲存中…") : (en ? "Submit body report" : "送出身體回報")}
                </Button>
              </Row>
              <Text variant="caption" as="p" className="body-privacy">
                {en
                  ? "Whether you hurt and how much is shared separately from your note: a coach who sees the summary cannot read the note without your consent. "
                  : "「有沒有不適／程度」與「補充說明」分開授權：教練看得到摘要，不代表能讀到你寫的內容。"}
                <Link to="/app/team">{en ? "Manage sharing" : "調整分享範圍"}</Link>
              </Text>
            </Stack>
          </form>
        </GlassPanel>

        <div className="body-aside">
          {(guidanceLoading || guidance) && (
            <GlassPanel
              as="section"
              padding="lg"
              className="body-result"
              tone={guidance ? (urgencyTone === "critical" ? "danger" : urgencyTone) : "good"}
              role="status"
              aria-live="polite"
              aria-label={en ? "Triage result" : "分流結果"}
            >
              {guidanceLoading || !guidance ? (
                <Notice tone="neutral" icon="info">
                  {en ? "Checking your report…" : "正在判讀你的回報…"}
                </Notice>
              ) : (
                <Stack gap={2}>
                  <Row gap={2} wrap>
                    <Badge tone={URGENCY_TONE[guidance.urgency]} dot>
                      {URGENCY_LABEL[guidance.urgency][locale]}
                    </Badge>
                    <Badge tone={guidance.running_allowed ? "good" : "critical"}>
                      {guidance.running_allowed ? (en ? "Running allowed" : "可跑步") : (en ? "Do not run" : "先不要跑")}
                    </Badge>
                  </Row>
                  <strong className="body-result-title">{guidance.summary}</strong>
                  {guidance.next_steps.length > 0 && (
                    <ul className="body-next-steps">
                      {guidance.next_steps.map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ul>
                  )}
                  {guidance.citations.map((citation) => (
                    <Text variant="caption" as="div" key={citation.evidence_id}>
                      {en ? "Source: " : "來源："}{citation.publisher} — {citation.title}
                      <br />
                      <a href={citation.source_url} target="_blank" rel="noreferrer">
                        {citation.source_url}
                      </a>
                    </Text>
                  ))}
                  <Text variant="caption">{guidance.disclaimer}</Text>
                  <Text variant="caption" className="body-provenance">
                    {guidance.provider_name} · {guidance.rule_version}
                    {guidance.used_fallback ? (en ? " · fallback" : "（備援）") : ""}
                  </Text>
                  <button
                    type="button"
                    className="ath-cta body-ask"
                    onClick={() => openCoach(reportContextOf(guidance))}
                  >
                    <FirstAidKit size={18} aria-hidden="true" />
                    <span>{en ? "Ask your coach about this" : "帶著這份回報去問教練"}</span>
                  </button>
                </Stack>
              )}
            </GlassPanel>
          )}

          <GlassPanel as="section" padding="lg" aria-labelledby="body-history-title">
            <h2 className="body-aside-title" id="body-history-title">
              {en ? "Past reports" : "回報紀錄"}
              <span className="body-count">{injuryReports.length}</span>
            </h2>
            {injuryReports.length === 0 ? (
              <EmptyState icon="heart" title={en ? "No reports yet" : "還沒有回報紀錄"} />
            ) : (
              <ul className="body-history">
                {injuryReports.slice(0, HISTORY_SHOWN).map((report) => {
                  const detail = injuryDetails.find((d) => d.injuryReportId === report.id);
                  return (
                    <Stack as="li" gap={1} key={report.id} className="body-report-item">
                      <Row gap={2} wrap>
                        <Text variant="label" as="strong">{dateLabel(report.localDate)}</Text>
                        <SeverityBadge band={report.severityBand} />
                        {report.hasIssue && report.bodyPart && <Badge>{report.bodyPart}</Badge>}
                      </Row>
                      {detail?.freeText && <Text variant="caption" as="p">{detail.freeText}</Text>}
                    </Stack>
                  );
                })}
              </ul>
            )}
          </GlassPanel>

          <Surface as="details" padding="none" className="body-guidance">
            <summary>{en ? "What your coach can see" : "教練看得到什麼"}</summary>
            <Stack gap={3} className="body-guidance-body">
              <Row justify="between" gap={3}>
                <Stack gap={1}>
                  <Text variant="label" as="div">{en ? "Discomfort and severity" : "有無不適／程度"}</Text>
                  <Text variant="caption" as="div">{en ? "Body report summary" : "身體回報摘要"}</Text>
                </Stack>
                <Badge tone={statusGranted ? "warning" : "good"} dot>
                  {statusGranted ? (en ? "Shared" : "已授權") : (en ? "Not shared" : "未授權")}
                </Badge>
              </Row>
              <Row justify="between" gap={3}>
                <Stack gap={1}>
                  <Text variant="label" as="div">{en ? "Note" : "補充說明"}</Text>
                  <Text variant="caption" as="div">{en ? "What you wrote" : "你寫的文字內容"}</Text>
                </Stack>
                <Badge tone={detailGranted ? "warning" : "good"} dot>
                  {detailGranted ? (en ? "Shared" : "已授權") : (en ? "Not shared" : "未授權")}
                </Badge>
              </Row>
              {activeTeam && (
                <Text variant="caption" as="p">
                  {en
                    ? `Team: ${activeTeam.teamName} · Coach: ${activeTeam.coachName}`
                    : `團隊：${activeTeam.teamName}・教練：${activeTeam.coachName}`}
                </Text>
              )}
              <Text variant="caption" as="p">{HEALTH_COACH_DISCLAIMER[locale]}</Text>
            </Stack>
          </Surface>
        </div>
      </div>
    </>
  );
}

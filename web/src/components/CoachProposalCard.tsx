import { useState } from "react";
import { CheckCircle, PaperPlaneTilt, Sparkle, X } from "@phosphor-icons/react";
import type { CoachProposal } from "../lib/coachConversation.ts";
import { conditionsCostLabel, planTypeLabel } from "../lib/planLabels.ts";
import type { Locale } from "../lib/planLabels.ts";

/** A plan the AI health coach worked out from what the Athlete just said.
 *
 *  It states what changed and what it produced, so the Athlete can judge it
 *  rather than trust it. Nothing about their day changes until they accept --
 *  and on a day their coach scheduled they cannot accept it at all, only send
 *  it to the coach, who decides (ADR 0003).
 */
export function CoachProposalCard({
  proposal,
  locale,
  onAccept,
  onShare,
  onDismiss,
}: {
  proposal: CoachProposal;
  locale: Locale;
  /** Resolves to a message when nothing was applied. */
  onAccept: () => Promise<string | null | void> | void;
  onShare: () => Promise<void>;
  onDismiss: () => void;
}) {
  const en = locale === "en";
  const [applying, setApplying] = useState(false);
  const [sharing, setSharing] = useState<"idle" | "sending" | "sent">("idle");
  const [notice, setNotice] = useState<string | null>(null);
  const locked = !proposal.selfApplyAllowed;

  const changes = proposal.changedFacts
    .map((fact) => describeChange(fact, proposal, en))
    .filter((line): line is string => line !== null);

  const costText = conditionsCostLabel(proposal.speedLossPct, locale);

  // A proposal can be about another day -- a race, or a session the Athlete
  // is planning ahead. Saying "today" then would be simply untrue.
  const isForToday = proposal.facts.localDate === localDateToday();
  const applyLabel = isForToday
    ? en
      ? "Use this today"
      : "套用到今天"
    : en
      ? `Use this on ${proposal.facts.localDate}`
      : `套用到 ${proposal.facts.localDate}`;

  return (
    <div
      style={{
        alignSelf: "flex-start",
        maxWidth: "96%",
        padding: "14px 16px",
        borderRadius: 14,
        backgroundColor: "var(--accent-soft)",
        border: "1px solid var(--accent-ring)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        animation: "fadeIn 0.3s ease-out",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <Sparkle size={16} weight="fill" color="var(--accent)" aria-hidden="true" />
        <span style={{ fontWeight: 800, fontSize: 13.5, color: "var(--accent-ink)" }}>
          {en ? "A plan for what you described" : "依你描述重新安排的課表"}
        </span>
      </div>

      {changes.length > 0 && (
        <div style={{ fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.6 }}>
          <div style={{ fontWeight: 700, marginBottom: 2 }}>
            {en ? "Because you said:" : "因為你提到："}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {changes.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {proposal.candidates.map((candidate, index) => (
          <div
            key={candidate.candidateId}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: 10,
              padding: "8px 11px",
              borderRadius: 9,
              backgroundColor: index === 0 ? "var(--surface)" : "transparent",
              border: index === 0 ? "1px solid var(--accent-ring)" : "1px solid transparent",
            }}
          >
            <span style={{ fontWeight: index === 0 ? 750 : 600, fontSize: 13 }}>
              {index === 0 && (
                <span style={{ color: "var(--accent)", marginRight: 5 }}>
                  {en ? "Suggested" : "建議"}
                </span>
              )}
              {planTypeLabel(candidate.workoutType, locale)}
            </span>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {candidate.durationMinutes > 0
                ? `${candidate.durationMinutes} ${en ? "min" : "分鐘"}`
                : en
                  ? "No run"
                  : "不跑"}
              {candidate.distanceKm > 0 ? ` · ${candidate.distanceKm} km` : ""}
            </span>
          </div>
        ))}
      </div>

      {costText && (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {en ? "Pace: " : "配速："}
          {costText}
          {proposal.pacingIsExtrapolated &&
            (en
              ? " (beyond what the research measured — a rough estimate)"
              : "（超出研究實測範圍，僅供粗估）")}
        </div>
      )}

      {proposal.abstained && (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {en
            ? "Not enough of your data to personalise yet — this is the conservative order."
            : "你的資料還不足以個人化，這是保守排序的版本。"}
        </div>
      )}

      {locked && (
        <div
          style={{
            fontSize: 12.5,
            lineHeight: 1.6,
            padding: "8px 11px",
            borderRadius: 9,
            backgroundColor: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--text-2)",
          }}
        >
          {en ? "Your coach has scheduled this day: " : "教練已安排這天的課表："}
          <strong>{proposal.coachAssigned.join("、")}</strong>
          <div style={{ color: "var(--text-muted)" }}>
            {en
              ? "This suggestion can't replace it. Send it to your coach to talk it over."
              : "這份建議不能直接取代教練的課表，可以傳給教練討論。"}
          </div>
        </div>
      )}

      {notice && (
        <div role="status" style={{ fontSize: 12.5, color: "var(--text-2)" }}>
          {notice}
        </div>
      )}

      {!proposal.canSendToCoach && (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {en
            ? "This account is not an athlete on any team, so there is no coach to send this to."
            : "這個帳號不是任何隊伍的選手（例如教練帳號），所以沒有可以傳送的教練。"}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 2, flexWrap: "wrap" }}>
        {!locked && (
          <button
            type="button"
            disabled={applying}
            onClick={async () => {
              setApplying(true);
              try {
                const refused = await onAccept();
                if (refused) setNotice(refused);
              } finally {
                setApplying(false);
              }
            }}
            style={{
              flex: 1,
              padding: "9px 12px",
              borderRadius: 9,
              border: "none",
              backgroundColor: "var(--accent)",
              color: "var(--accent-on)",
              fontWeight: 750,
              fontSize: 13,
              cursor: applying ? "progress" : "pointer",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
            }}
          >
            <CheckCircle size={15} weight="bold" aria-hidden="true" />
            {applying ? (en ? "Applying…" : "套用中…") : applyLabel}
          </button>
        )}
        {proposal.canSendToCoach && (
        <button
          type="button"
          disabled={sharing !== "idle"}
          onClick={async () => {
            setSharing("sending");
            setNotice(null);
            try {
              await onShare();
              setSharing("sent");
            } catch (error) {
              setSharing("idle");
              setNotice(error instanceof Error && error.message ? error.message : en ? "Could not send." : "傳送失敗");
            }
          }}
          style={{
            flex: locked ? 1 : undefined,
            padding: "9px 12px",
            borderRadius: 9,
            border: locked ? "none" : "1px solid var(--accent-ring)",
            backgroundColor: locked ? "var(--accent)" : "var(--surface)",
            color: locked ? "var(--accent-on)" : "var(--accent-ink)",
            fontWeight: 700,
            fontSize: 13,
            cursor: sharing === "sending" ? "progress" : sharing === "sent" ? "default" : "pointer",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
          }}
        >
          <PaperPlaneTilt size={14} weight="bold" aria-hidden="true" />
          {sharing === "sent"
            ? en ? "Sent to your coach" : "已傳給教練"
            : sharing === "sending"
              ? en ? "Sending…" : "傳送中…"
              : en ? "Send to my coach" : "傳給教練"}
        </button>
        )}
        <button
          type="button"
          onClick={onDismiss}
          style={{
            padding: "9px 12px",
            borderRadius: 9,
            border: "1px solid var(--border)",
            backgroundColor: "var(--surface)",
            color: "var(--text-2)",
            fontWeight: 650,
            fontSize: 13,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
          }}
        >
          <X size={14} aria-hidden="true" />
          {en ? "Not now" : "先不要"}
        </button>
      </div>

      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
        {sharing === "sent"
          ? en
            ? "Your coach will see it in your one-to-one chat and decides whether to schedule it."
            : "教練會在你們的一對一聊天室看到這份建議，由教練決定要不要排進課表。"
          : en
            ? "Nothing has changed yet."
            : locked
              ? "教練的課表不會因為這份建議而改變。"
              : isForToday
                ? "在你按下套用之前，今天的課表不會有任何變動。"
                : "在你按下套用之前，你的課表不會有任何變動。"}
      </div>
    </div>
  );
}

/** The Athlete's own local date, in the same "YYYY-MM-DD" form the backend
 *  works in -- built from local parts rather than an ISO string, which would
 *  shift the date for anyone east or west of UTC. */
function localDateToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function describeChange(fact: string, proposal: CoachProposal, en: boolean): string | null {
  const facts = proposal.facts;
  switch (fact) {
    case "available_minutes":
      return facts.availableMinutes === null
        ? null
        : en
          ? `you have about ${facts.availableMinutes} minutes`
          : `你今天大約有 ${facts.availableMinutes} 分鐘`;
    case "temperature_c":
      return facts.temperatureC === null
        ? null
        : en
          ? `it is around ${Math.round(facts.temperatureC)}°C`
          : `氣溫大約 ${Math.round(facts.temperatureC)}°C`;
    case "humidity_pct":
      return facts.humidityPct === null
        ? null
        : en
          ? `humidity is around ${Math.round(facts.humidityPct)}%`
          : `濕度大約 ${Math.round(facts.humidityPct)}%`;
    case "reported_body_part":
      return facts.reportedBodyPart === null
        ? null
        : en
          ? `you are feeling something in your ${facts.reportedBodyPart}`
          : `你的${facts.reportedBodyPart}有些狀況`;
    case "reported_severity_band":
      return null; // Covered by the body-part line; saying it twice reads oddly.
    case "local_date":
      return en ? `you are asking about ${facts.localDate}` : `你問的是 ${facts.localDate}`;
    default:
      return null;
  }
}

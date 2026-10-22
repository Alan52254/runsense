import { useState } from "react";
import { CheckCircle, PaperPlaneTilt, X } from "@phosphor-icons/react";
import type { CoachProposal } from "../lib/coachConversation.ts";
import { conditionsCostLabel, paceLabel, paceRangeLabel, planTypeLabel } from "../lib/planLabels.ts";
import type { Locale } from "../lib/planLabels.ts";

/** A plan the health coach worked out from what the Athlete just said.
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
  // "confirming": the Athlete is shown exactly what the coach will see
  // before anything leaves their private conversation
  const [sharing, setSharing] = useState<"idle" | "confirming" | "sending" | "sent">("idle");
  const [notice, setNotice] = useState<string | null>(null);
  const locked = !proposal.selfApplyAllowed;

  const changes = proposal.changedFacts
    .map((fact) => describeChange(fact, proposal, en))
    .filter((line): line is string => line !== null);

  async function send() {
    setSharing("sending");
    try {
      await onShare();
      setSharing("sent");
    } catch (error) {
      setSharing("idle");
      setNotice(error instanceof Error && error.message ? error.message : en ? "Could not send." : "傳送失敗");
    }
  }

  const top = proposal.candidates[0];
  const topLine = top
    ? [
        planTypeLabel(top.workoutType, locale),
        top.durationMinutes > 0 ? `${top.durationMinutes} ${en ? "min" : "分鐘"}` : null,
        top.distanceKm > 0 ? `${top.distanceKm} km` : null,
        paceRangeLabel(top.paceRangeSPerKm),
      ].filter(Boolean).join(" · ")
    : "";

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
    <section className="cc-proposal" aria-label={en ? "Suggested plan" : "建議課表"}>
      <h3 className="cc-proposal-title">
        {en ? "A plan for what you described" : "依你描述重新安排的課表"}
      </h3>

      {changes.length > 0 && (
        <div className="cc-proposal-why">
          <span className="cc-proposal-why-label">{en ? "Because you said:" : "因為你提到："}</span>
          <ul>
            {changes.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      <ul className="cc-proposal-options">
        {proposal.candidates.map((candidate, index) => (
          <li
            key={candidate.candidateId}
            className={index === 0 ? "cc-proposal-option is-top" : "cc-proposal-option"}
          >
            <span className="cc-proposal-option-name">
              {index === 0 && (
                <span className="cc-proposal-tag">{en ? "Suggested" : "建議"}</span>
              )}
              {planTypeLabel(candidate.workoutType, locale)}
            </span>
            <span className="cc-proposal-option-detail">
              {candidate.durationMinutes > 0
                ? `${candidate.durationMinutes} ${en ? "min" : "分鐘"}`
                : en
                  ? "No run"
                  : "不跑"}
              {candidate.distanceKm > 0 ? ` · ${candidate.distanceKm} km` : ""}
              {candidate.paceRangeSPerKm ? ` · ${paceRangeLabel(candidate.paceRangeSPerKm)}` : ""}
            </span>
          </li>
        ))}
      </ul>

      {proposal.easyPace && proposal.candidates.some((c) => c.paceRangeSPerKm) && (
        <p className="cc-proposal-note">
          {en
            ? `Paces come from your own ${proposal.easyPace.runs} easy runs in the last ${proposal.easyPace.days} days (median ${paceLabel(proposal.easyPace.sPerKm)}), not a model.`
            : `配速是從你近 ${proposal.easyPace.days} 天的 ${proposal.easyPace.runs} 次輕鬆跑算出來的（中位數 ${paceLabel(proposal.easyPace.sPerKm)}），不是模型猜的。`}
        </p>
      )}

      {costText && (
        <p className="cc-proposal-note">
          {en ? "Pace: " : "配速："}
          {costText}
          {proposal.pacingIsExtrapolated &&
            (en
              ? " (beyond what the research measured — a rough estimate)"
              : "（超出研究實測範圍，僅供粗估）")}
        </p>
      )}

      {proposal.abstained && (
        <p className="cc-proposal-note">
          {en
            ? "Not enough of your data to personalise yet — this is the conservative order."
            : "你的資料還不足以個人化，這是保守排序的版本。"}
        </p>
      )}

      {locked && (
        <div className="cc-proposal-locked">
          {en ? "Your coach has scheduled this day: " : "教練已安排這天的課表："}
          <strong>{proposal.coachAssigned.join("、")}</strong>
          <p className="cc-proposal-note">
            {en
              ? "This suggestion can't replace it. Send it to your coach to talk it over."
              : "這份建議不能直接取代教練的課表，可以傳給教練討論。"}
          </p>
        </div>
      )}

      {notice && (
        <p role="status" className="cc-proposal-notice">
          {notice}
        </p>
      )}

      {!proposal.canSendToCoach && (
        <p className="cc-proposal-note">
          {en
            ? "This account is not an athlete on any team, so there is no coach to send this to."
            : "這個帳號不是任何隊伍的選手（例如教練帳號），所以沒有可以傳送的教練。"}
        </p>
      )}

      {sharing === "confirming" && (
        <div
          role="dialog"
          aria-label={en ? "What your coach will see" : "教練會看到的內容"}
          className="cc-proposal-confirm"
        >
          <strong>{en ? "Your coach will see:" : "以下內容會讓教練看到："}</strong>
          <ul>
            <li>
              {proposal.facts.localDate}：{topLine}
            </li>
            {proposal.label && (
              <li>
                {en ? "Titled: " : "標題："}
                {proposal.label}
              </li>
            )}
            {changes.map((line) => (
              <li key={line}>{line}</li>
            ))}
            {locked && (
              <li>
                {en ? "Your coach's session that day: " : "這天教練原本的課表："}
                {proposal.coachAssigned.join("、")}
              </li>
            )}
          </ul>
          <p className="cc-proposal-note">
            {en
              ? "Nothing else from this conversation is sent."
              : "這段對話的其他內容都不會傳出去。"}
          </p>
          <div className="cc-proposal-actions">
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void send()}>
              {en ? "Send" : "確認傳送"}
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => setSharing("idle")}>
              {en ? "Cancel" : "取消"}
            </button>
          </div>
        </div>
      )}

      <div className="cc-proposal-actions">
        {!locked && (
          <button
            type="button"
            className="btn btn-primary cc-proposal-apply"
            disabled={applying}
            aria-busy={applying || undefined}
            onClick={async () => {
              setApplying(true);
              try {
                const refused = await onAccept();
                if (refused) setNotice(refused);
              } finally {
                setApplying(false);
              }
            }}
          >
            <CheckCircle size={16} weight="bold" aria-hidden="true" />
            {applying ? (en ? "Applying…" : "套用中…") : applyLabel}
          </button>
        )}
        {proposal.canSendToCoach && (
          <button
            type="button"
            className={locked ? "btn btn-primary cc-proposal-apply" : "btn btn-secondary"}
            disabled={sharing !== "idle"}
            aria-busy={sharing === "sending" || undefined}
            onClick={() => {
              setNotice(null);
              setSharing("confirming");
            }}
          >
            <PaperPlaneTilt size={15} weight="bold" aria-hidden="true" />
            {sharing === "sent"
              ? en ? "Sent to your coach" : "已傳給教練"
              : sharing === "sending"
                ? en ? "Sending…" : "傳送中…"
                : en ? "Send to my coach" : "傳給教練"}
          </button>
        )}
        <button type="button" className="btn btn-ghost" onClick={onDismiss}>
          <X size={15} aria-hidden="true" />
          {en ? "Not now" : "先不要"}
        </button>
      </div>

      <p className="cc-proposal-foot">
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
      </p>
    </section>
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

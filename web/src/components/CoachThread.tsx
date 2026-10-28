import { useRef } from "react";
import type { CSSProperties } from "react";
import { BookOpenText, WarningCircle } from "@phosphor-icons/react";
import { MarkdownMessage } from "./MarkdownMessage.tsx";
import { CoachAvatar } from "./CoachAvatar.tsx";
import { CoachOpening } from "./CoachOpening.tsx";
import { CoachProposalCard } from "./CoachProposalCard.tsx";
import { CoachThinking } from "./CoachThinking.tsx";
import { Text } from "./Text.tsx";
import { followUpChips, shouldEnterAnimated, threadStage, undeliveredIndex } from "../lib/coachChatUi.ts";
import type { FollowUp } from "../lib/coachChatUi.ts";
import { citationsOf, isBusy, pendingProposal, visibleText } from "../lib/coachConversation.ts";
import type { CoachPhase, ThinkingStep } from "../lib/coachConversation.ts";
import type { OpeningCardText } from "../lib/coachPrompts.ts";
import { useCoachChat } from "../state/CoachChatContext.tsx";
import { useLocale } from "../state/LocaleContext.tsx";
import { useWorkspace } from "../state/WorkspaceContext.tsx";

/** The conversation: your messages as soft bubbles on the right, the coach's
 *  words as plain text with its face at the left. Steps, sources and the
 *  proposal sit under the message they belong to; follow-ups sit under the
 *  last answer. An untouched thread is the opening instead. */
export function CoachThread({ en, openingCards }: { en: boolean; openingCards: OpeningCardText[] }) {
  const coach = useCoachChat();
  const { phase, messages } = coach;
  const { locale } = useLocale();
  const { liveTrainingPlan } = useWorkspace();
  const answerText = visibleText(phase);
  const citations = citationsOf(phase);
  const awaitingDecision = pendingProposal(phase);
  // the plan the Athlete has for the day the suggestion is about
  const topNow = liveTrainingPlan?.candidates[0];
  const currentPlan =
    awaitingDecision && topNow && liveTrainingPlan?.local_date === awaitingDecision.facts.localDate
      ? { workoutType: topNow.workout_type, minutes: topNow.duration_minutes, km: topNow.distance_km }
      : null;

  // What was on screen when this thread mounted. A message that was already
  // there never re-animates (drawer reopened, tab switched back), and the
  // blocks of the turn in progress stay calm until the next question.
  const hasUserMessage = messages.some((message) => message.role === "user");
  const mounted = useRef({ count: messages.length, kind: phase.kind, opening: !hasUserMessage && phase.kind === "idle" });
  const calm = mounted.current.kind !== "idle" && messages.length === mounted.current.count;

  const followUps = followUpChips(phase, { en, today: localDate(new Date()) });
  const stage = threadStage({ hasUserMessage, phaseKind: phase.kind, hasFollowUps: followUps.length > 0 });
  const busy = isBusy(phase);
  const undelivered = undeliveredIndex(messages, phase);
  const runFollowUp = (chip: FollowUp) => {
    if (chip.action.kind === "send") void coach.send(chip.action.text);
    else coach.openCitation(chip.action.citation);
  };

  // the greeting belongs to the opening; the thread starts at the first question
  const greeting = messages[0]?.role === "assistant" ? messages[0].content : "";

  return (
    <div
      className="cc-thread"
      role="log"
      aria-live="polite"
      aria-label={en ? "Conversation with your coach" : "與教練的對話"}
      data-calm={calm || undefined}
      data-opening={mounted.current.opening || undefined}
      data-stage={stage.openingCards ? "opening" : undefined}
    >
      {mounted.current.opening && (
        <CoachOpening greeting={greeting} cards={openingCards} collapsed={!stage.openingCards} busy={phase.kind !== "idle"} />
      )}

      {messages.map((message, index) => {
        if (index === 0 && message.role === "assistant") return null;
        if (message.role === "user") {
          return (
            <div
              key={index}
              className={`cc-msg cc-msg--user${shouldEnterAnimated(index, mounted.current.count) ? " cc-enter-user" : ""}`}
            >
              <p className="cc-msg-text">{message.content}</p>
              {index === undelivered && (
                <Text variant="caption" className="cc-undelivered">{en ? "Not delivered" : "未送達"}</Text>
              )}
            </div>
          );
        }
        return (
          <div key={index} className="cc-coach-row">
            <CoachAvatar size="sm" />
            <div className="cc-msg">
              <MarkdownMessage content={message.content} />
            </div>
          </div>
        );
      })}

      {phase.kind !== "idle" && phase.kind !== "failed" && (
        <CoachThinking steps={stepsOfPhase(phase)} stillWorking={phase.kind === "thinking"} busy={busy} en={en} />
      )}

      {answerText && phase.kind === "failed" && (
        // Not an answer. The coach could not be reached, and saying so in the
        // same form a real answer uses would be dishonest.
        <div className="cc-unavailable cc-enter-coach" role="status">
          <WarningCircle size={18} weight="fill" aria-hidden="true" className="cc-unavailable-icon" />
          <div>
            <strong>{en ? "Coach unavailable" : "教練目前連線不上"}</strong>
            <p>{answerText}</p>
            <button type="button" className="cc-chip cc-retry" onClick={() => void coach.retry()}>
              {en ? "Resend" : "重新傳送"}
            </button>
          </div>
        </div>
      )}

      {answerText && phase.kind !== "failed" && (
        <div className="cc-msg cc-indent cc-enter-coach">
          <MarkdownMessage content={answerText} isStreaming={phase.kind === "streaming"} />
        </div>
      )}

      {answerText && phase.kind !== "failed" && citations.length > 0 && (
        <div className="cc-citations cc-indent cc-enter-coach">
          <span className="cc-citations-label">{en ? "Based on" : "依據"}</span>
          <ul className="cc-citation-list">
            {citations.map((citation, index) => (
              <li key={citation.evidenceId}>
                <button
                  type="button"
                  className="cc-citation"
                  style={{ "--i": index } as CSSProperties}
                  onClick={() => coach.openCitation(citation)}
                >
                  <BookOpenText size={18} aria-hidden="true" className="cc-citation-icon" />
                  <span className="cc-citation-text">
                    <span className="cc-citation-title">{citation.title}</span>
                    {citation.publisher && <span className="cc-citation-pub">{citation.publisher}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {awaitingDecision && (
        <CoachProposalCard
          key={awaitingDecision.id}
          proposal={awaitingDecision}
          locale={locale}
          current={currentPlan}
          onAccept={() => coach.acceptProposal(awaitingDecision)}
          onShare={() => coach.shareProposal(awaitingDecision)}
          onDismiss={() => coach.dismissProposal(awaitingDecision)}
        />
      )}

      {stage.followUps && (
        <div className="cc-follows cc-indent" role="group" aria-label={en ? "Follow-up questions" : "接著問"}>
          {followUps.map((chip, index) => (
            <button
              key={`${phase.kind}-${chip.label}`}
              type="button"
              className="cc-chip cc-chip--follow"
              style={{ "--i": index } as CSSProperties}
              disabled={busy && chip.action.kind === "send"}
              onClick={() => runFollowUp(chip)}
            >
              {chip.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function localDate(now: Date): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function stepsOfPhase(phase: CoachPhase): ThinkingStep[] {
  switch (phase.kind) {
    case "thinking":
    case "streaming":
    case "proposal":
    case "answered":
      return phase.steps;
    default:
      return [];
  }
}

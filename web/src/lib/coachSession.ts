/** The health-coach conversation, without React.
 *
 *  Owns the transcript and the conversation's phase, and everything that
 *  happens between them: folding the previous answer into the transcript
 *  before the next question, refusing a second question while the coach is
 *  still answering, wording an outage for the Athlete, refreshing the plan
 *  after a proposal is applied, and adding a body report once.
 *
 *  It talks to the server only through a CoachChatTransport, so node:test
 *  drives it with an in-memory transport and the app with the API one.
 */

import type { CoachChatMessage, CoachStreamEvent } from "../data/apiClient.ts";
import { IDLE, coachPhaseReducer, isBusy, visibleText } from "./coachConversation.ts";
import type { CoachEvent, CoachPhase, CoachProposal } from "./coachConversation.ts";
import { appendOnce, reportContextMessage } from "./coachChatSession.ts";
import type { CoachReportContext } from "./coachChatSession.ts";
import { toProposal, toThinkingStep } from "./coachWire.ts";

/** What the conversation needs from the server. One per signed-in user;
 *  no transport means nobody is signed in. */
export interface CoachChatTransport {
  /** Streams the answer to `history`; resolves once the stream ends, rejects
   *  when it drops. `onComplete` fires when the server says it is done. */
  streamMessage(
    history: CoachChatMessage[],
    onEvent: (event: CoachStreamEvent) => void,
    onComplete: () => void,
  ): Promise<void>;
  acceptProposal(proposalId: string): Promise<{ applied: boolean; reason?: string | null }>;
  dismissProposal(proposalId: string): Promise<unknown>;
  shareProposal(proposalId: string): Promise<unknown>;
  /** The Athlete's plan changed; the rest of the app should show it. */
  refreshPlan(): Promise<void>;
}

export interface CoachSessionState {
  messages: CoachChatMessage[];
  phase: CoachPhase;
}

export interface CoachSession {
  getState(): CoachSessionState;
  subscribe(listener: () => void): () => void;
  /** Null when ignored (empty, or the coach is still answering); otherwise
   *  settles once the answer has arrived or failed. */
  send(text: string): Promise<void> | null;
  /** Null when applied; otherwise what to tell the Athlete. */
  acceptProposal(proposal: CoachProposal): Promise<string | null>;
  /** Hands the suggestion to the coach; scheduling stays the coach's call. */
  shareProposal(proposal: CoachProposal): Promise<void>;
  dismissProposal(proposal: CoachProposal): void;
  /** Restates a body report in the conversation, once. */
  addReport(report: CoachReportContext): void;
}

export function createCoachSession(options: {
  /** Read on every call: the signed-in user can change under the session. */
  transport: () => CoachChatTransport | null;
  english: () => boolean;
  welcome: CoachChatMessage[];
}): CoachSession {
  let state: CoachSessionState = { messages: options.welcome, phase: IDLE };
  let sending = false;
  const listeners = new Set<() => void>();

  const set = (next: Partial<CoachSessionState>) => {
    state = { ...state, ...next };
    for (const listener of listeners) listener();
  };
  const dispatch = (event: CoachEvent) => set({ phase: coachPhaseReducer(state.phase, event) });

  async function stream(history: CoachChatMessage[], unavailableText: string): Promise<void> {
    const transport = options.transport();
    if (!transport) {
      dispatch({ type: "FAILED", text: unavailableText });
      return;
    }
    let sawText = false;
    try {
      await transport.streamMessage(
        history,
        (event) => {
          if (event.kind === "delta") {
            sawText = true;
            dispatch({ type: "DELTA", delta: event.delta });
          } else if (event.kind === "step") {
            const step = toThinkingStep(event.step);
            if (step) dispatch({ type: "STEP", step });
          } else if (event.kind === "proposal") {
            const proposal = toProposal(event.proposal);
            if (proposal) dispatch({ type: "PROPOSED", proposal });
          }
        },
        () => dispatch({ type: "SETTLED" }),
      );
      if (!sawText) dispatch({ type: "FAILED", text: unavailableText });
    } catch {
      // A dropped stream keeps whatever already arrived.
      if (sawText) dispatch({ type: "SETTLED" });
      else dispatch({ type: "FAILED", text: unavailableText });
    }
  }

  return {
    getState: () => state,

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    send(rawText) {
      const text = rawText.trim();
      if (!text || isBusy(state.phase) || sending) return null;
      sending = true;

      // The previous answer lives in the phase until now; fold it into the
      // transcript so it is not lost, and so the coach can see what it said.
      const priorAnswer = state.phase.kind === "failed" ? "" : visibleText(state.phase).trim();
      const transcript: CoachChatMessage[] = priorAnswer
        ? [...state.messages, { role: "assistant", content: priorAnswer }]
        : state.messages;
      const history: CoachChatMessage[] = [...transcript, { role: "user", content: text }];

      set({ messages: history });
      dispatch({ type: "ASKED" });

      const unavailableText = options.english()
        ? "Your coach cannot be reached right now. Your plan and any safety guidance you already have still stand."
        : "目前聯絡不上教練。你既有的課表與安全建議仍然有效；若有持續的急性疼痛，請諮詢專業醫師。";

      return stream(history, unavailableText).finally(() => {
        sending = false;
      });
    },

    async acceptProposal(proposal) {
      const en = options.english();
      const transport = options.transport();
      if (!transport || !proposal.id) return en ? "Sign in again to apply this plan." : "請重新登入後再套用課表。";
      const outcome = await transport.acceptProposal(proposal.id);
      if (!outcome.applied && outcome.reason === "COACH_SCHEDULED") {
        // the coach scheduled this day after the suggestion was made
        return en
          ? "Your coach has scheduled this day. Send this to your coach instead."
          : "教練已經排了這天的課表，無法直接套用。可以把建議傳給教練討論。";
      }
      dispatch({ type: "PROPOSAL_ACCEPTED" });
      await transport.refreshPlan();
      return null;
    },

    async shareProposal(proposal) {
      const transport = options.transport();
      if (!transport || !proposal.id) {
        throw new Error(options.english() ? "Sign in again to share." : "請重新登入後再分享。");
      }
      await transport.shareProposal(proposal.id);
    },

    dismissProposal(proposal) {
      dispatch({ type: "PROPOSAL_DISMISSED" });
      const transport = options.transport();
      if (transport && proposal.id) {
        void transport.dismissProposal(proposal.id).catch(() => {
          // Declining is the Athlete's decision either way; a failed record of
          // it must not become their problem.
        });
      }
    },

    addReport(report) {
      const messages = appendOnce(state.messages, {
        role: "assistant",
        content: reportContextMessage(report, options.english()),
      });
      if (messages !== state.messages) set({ messages });
    },
  };
}

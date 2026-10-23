/** An in-memory CoachChatTransport: scripted replies, recorded calls. For
 *  node:test, where there is no server to stream from. */

import type { CoachChatMessage, CoachStreamEvent } from "../data/apiClient.ts";
import type { CoachChatTransport } from "./coachSession.ts";

export interface InMemoryCoachTransport extends CoachChatTransport {
  /** The history sent with each question, in order. */
  readonly sent: CoachChatMessage[][];
  readonly accepted: string[];
  readonly dismissed: string[];
  readonly shared: string[];
  readonly refreshes: number;
  /** Lets held streams finish (see `hold`). */
  release(): void;
}

export function inMemoryCoachTransport(script: {
  /** One list of events per question; questions past the end get none. */
  replies?: CoachStreamEvent[][];
  /** Drop the stream after its events instead of completing it. */
  failStream?: boolean;
  /** Keep each stream open until release() is called. */
  hold?: boolean;
  acceptOutcome?: { applied: boolean; reason?: string | null };
}): InMemoryCoachTransport {
  const sent: CoachChatMessage[][] = [];
  const accepted: string[] = [];
  const dismissed: string[] = [];
  const shared: string[] = [];
  let refreshes = 0;
  let released = !script.hold;
  const waiting: Array<() => void> = [];

  return {
    sent,
    accepted,
    dismissed,
    shared,
    get refreshes() {
      return refreshes;
    },
    release() {
      released = true;
      for (const resume of waiting.splice(0)) resume();
    },

    async streamMessage(history, onEvent, onComplete) {
      const events = script.replies?.[sent.length] ?? [];
      sent.push(history);
      if (!released) await new Promise<void>((resume) => waiting.push(resume));
      for (const event of events) onEvent(event);
      if (script.failStream) throw new Error("stream dropped");
      onComplete();
    },
    async acceptProposal(proposalId) {
      accepted.push(proposalId);
      return script.acceptOutcome ?? { applied: true };
    },
    async dismissProposal(proposalId) {
      dismissed.push(proposalId);
    },
    async shareProposal(proposalId) {
      shared.push(proposalId);
    },
    async refreshPlan() {
      refreshes += 1;
    },
  };
}

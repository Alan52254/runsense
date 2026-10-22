/** Pure pieces of the shared health-coach conversation (CoachChatProvider). */

export interface ChatLine {
  role: "user" | "assistant";
  content: string;
}

/** Adds a message unless the same text is already in the conversation, so
 *  opening the coach twice with one report does not repeat it. Returns the
 *  same array when nothing changed. */
export function appendOnce<M extends ChatLine>(messages: M[], message: M): M[] {
  return messages.some((existing) => existing.content === message.content)
    ? messages
    : [...messages, message];
}

/** What the Athlete's latest body report carries into the coach conversation. */
export interface CoachReportContext {
  bodyPart: string;
  severityBand: string;
  guidanceSummary: string;
  nextSteps: string[];
}

/** The coach's message that restates a body report's assessment. */
export function reportContextMessage(ctx: CoachReportContext, en: boolean): string {
  const lead = en ? "Your latest assessment: " : "你的最新評估結果：";
  return `${lead}${ctx.guidanceSummary}\n${ctx.nextSteps.join("\n")}`;
}

/** Focus trap for the drawer: given how many controls it holds, which one
 *  has focus (-1 when focus is outside it) and the Tab direction, the index to
 *  move focus to, or null to let the browser take the step. */
export function wrapFocusIndex(count: number, currentIndex: number, backwards: boolean): number | null {
  if (count === 0) return null;
  const first = 0;
  const last = count - 1;
  if (currentIndex < 0) return backwards ? last : first;
  if (backwards && currentIndex === first) return last;
  if (!backwards && currentIndex === last) return first;
  return null;
}

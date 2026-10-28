/** The coach composer's rules, without React: what a key does, when the send
 *  button works, how tall the box grows, which hint it shows. */

export interface ComposerKey {
  key: string;
  shiftKey: boolean;
  /** an IME is confirming a Chinese word */
  composing: boolean;
  input: string;
  lastUserMessage: string | null;
}

export type ComposerKeyAction = { kind: "send" } | { kind: "recall"; text: string } | { kind: "none" };

/** Enter sends, Shift+Enter breaks the line, ArrowUp in an empty box recalls
 *  the last thing the Athlete said. A word being confirmed is never a send. */
export function composerKeyAction(input: ComposerKey): ComposerKeyAction {
  if (input.composing) return { kind: "none" };
  if (input.key === "Enter" && !input.shiftKey) return { kind: "send" };
  if (input.key === "ArrowUp" && input.input === "" && input.lastUserMessage) {
    return { kind: "recall", text: input.lastUserMessage };
  }
  return { kind: "none" };
}

/** Sending needs words and a coach that is not mid-answer. Typing never waits. */
export function canSend(input: string, busy: boolean): boolean {
  return input.trim() !== "" && !busy;
}

export type ComposerHint = "ask" | "busy";

export function composerHint(busy: boolean): ComposerHint {
  return busy ? "busy" : "ask";
}

export const COMPOSER_MIN_PX = 40;
export const COMPOSER_MAX_PX = 168;

/** Grow with the text up to the cap, then scroll inside. An empty box is one
 *  line: its placeholder never decides the height. */
export function composerHeight(scrollHeight: number, empty: boolean): number {
  if (empty) return COMPOSER_MIN_PX;
  return Math.min(Math.max(scrollHeight, COMPOSER_MIN_PX), COMPOSER_MAX_PX);
}

/** The health-coach chat's interaction rules, without React.
 *
 *  Everything here is a decision the panel makes about what to show or do
 *  next: whether to follow the stream, which follow-up chips an answer
 *  earns, which figure a finished step lights, how a number counts up. Kept
 *  pure so node:test pins each one.
 */

import type { CoachChatMessage } from "../data/apiClient.ts";
import { usableAcwr } from "./acwr.ts";
import type { Citation, CoachPhase, ThinkingStep } from "./coachConversation.ts";
import { citationsOf, pendingProposal } from "./coachConversation.ts";

/* ---------------- scrolling ---------------- */

/** True while the reader is within `threshold` px of the end, so a growing
 *  answer may carry them along. Scrolled further up, they are reading. */
export function shouldStickToBottom(
  scrollTop: number,
  clientHeight: number,
  scrollHeight: number,
  threshold = 80,
): boolean {
  return scrollHeight - (scrollTop + clientHeight) <= threshold;
}

/** No question asked yet: the thread is the opening, which is read from its
 *  top. Following the end would scroll its face out of view on a short screen. */
export function startsAtTop(sentCount: number): boolean {
  return sentCount === 0;
}

/* ---------------- follow-up chips ---------------- */

export type FollowUpAction =
  | { kind: "send"; text: string }
  | { kind: "citation"; citation: Citation };

export interface FollowUp {
  id: string;
  label: string;
  action: FollowUpAction;
}

/** Up to three chips built only from what the finished answer itself holds:
 *  its proposal's stated minutes, the guidance it cited, and the training it
 *  read. Never model-generated; nothing sends until the Athlete taps. */
export function followUpChips(
  phase: CoachPhase,
  options: { en: boolean; today: string },
): FollowUp[] {
  if (phase.kind !== "answered" || !phase.text.trim()) return [];
  const { en, today } = options;
  const chips: FollowUp[] = [];

  const proposal = pendingProposal(phase);
  const minutes = proposal?.facts.availableMinutes ?? null;
  if (proposal && minutes !== null && minutes > 0) {
    const day = proposal.facts.localDate;
    const text = en
      ? `Fit the ${minutes}-minute version into ${!day || day === today ? "today" : day}`
      : `把 ${minutes} 分鐘版本排進${!day || day === today ? "今天" : ` ${day}`}`;
    chips.push({ id: "minutes", label: text, action: { kind: "send", text } });
  }

  const citation = citationsOf(phase)[0];
  if (citation) {
    chips.push({
      id: "citation",
      label: en ? "Read the source guidance" : "看這份指引原文",
      action: { kind: "citation", citation },
    });
  }

  const load = phase.steps.find((step) => step.kind === "READ_TRAINING_LOAD");
  if (load && load.kind === "READ_TRAINING_LOAD" && load.activityCount > 0) {
    const text = en
      ? `With my ${load.activityCount} sessions in 28 days, how should next week follow?`
      : `我近 28 天的 ${load.activityCount} 次訓練，下週該怎麼接？`;
    chips.push({ id: "load", label: text, action: { kind: "send", text } });
  }

  return chips.slice(0, 3);
}

/** What the thread shows besides the messages. The opening cards stand in
 *  for an empty thread; once the Athlete has asked, they are gone for good and
 *  the last answer's follow-ups sit under it instead. Never both. */
export function threadStage(input: {
  hasUserMessage: boolean;
  phaseKind: CoachPhase["kind"];
  hasFollowUps: boolean;
}): { openingCards: boolean; followUps: boolean } {
  return {
    openingCards: !input.hasUserMessage && input.phaseKind === "idle",
    followUps: input.phaseKind === "answered" && input.hasFollowUps,
  };
}

/** One face at a time: while the opening shows its large avatar, the header
 *  holds none. It appears with the first question, and always on the other
 *  sections. */
export function headerShowsFace(input: {
  tab: string;
  hasUserMessage: boolean;
  phaseKind: CoachPhase["kind"];
}): boolean {
  if (input.tab !== "chat") return true;
  return !threadStage({ hasUserMessage: input.hasUserMessage, phaseKind: input.phaseKind, hasFollowUps: false }).openingCards;
}

/* ---------------- messages ---------------- */

export function lastUserMessage(messages: CoachChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") return messages[i].content;
  }
  return null;
}

/** The question the coach never answered: the last message, when it is the
 *  Athlete's and the conversation ended in failure. Null otherwise. */
export function undeliveredIndex(messages: CoachChatMessage[], phase: CoachPhase): number | null {
  const last = messages.length - 1;
  return phase.kind === "failed" && last >= 0 && messages[last].role === "user" ? last : null;
}

/** Only a message that arrived after the thread mounted enters with motion;
 *  reopening the drawer must not replay the whole conversation. */
export function shouldEnterAnimated(index: number, mountedCount: number): boolean {
  return index >= mountedCount;
}

/* ---------------- tabs ---------------- */

export function tabDirection<T extends string>(
  order: readonly T[],
  from: T,
  to: T,
): "forward" | "back" | "none" {
  const a = order.indexOf(from);
  const b = order.indexOf(to);
  if (a === b || a < 0 || b < 0) return "none";
  return b > a ? "forward" : "back";
}

/* ---------------- the 教練正在看 strip ---------------- */

export type FigureId = "acute" | "chronic" | "ratio" | "weather";

/** The figures a finished step actually read. Reviewing guidance or weighing
 *  options reads none of them, so those steps light nothing. */
export function figuresUsedBy(step: ThinkingStep): FigureId[] {
  if (step.kind !== "READ_TRAINING_LOAD") return [];
  const used: FigureId[] = ["acute", "chronic"];
  if (usableAcwr(step.loadRatio) !== null) used.push("ratio");
  return used;
}

/** The figures the last finished step read; the 教練正在看 chip shows a dot
 *  for as long as this is not empty. */
export function litFigures(phase: CoachPhase): Set<FigureId> {
  if (phase.kind !== "thinking" && phase.kind !== "streaming" && phase.kind !== "proposal" && phase.kind !== "answered") {
    return new Set();
  }
  const last = phase.steps.at(-1);
  return new Set(last ? figuresUsedBy(last) : []);
}

export interface FigureInputs {
  acuteLoad: number | null;
  chronicLoad: number | null;
  loadRatio: number | null;
  /** days in the last 7 with a recorded session */
  trainingDays7: number;
  trainingDays28: number;
  temperatureC: number | null;
}

/** One line under each figure: where it comes from, or why it is bare. */
export function figureSources(input: FigureInputs, en: boolean): Record<FigureId, string> {
  const noData = en ? "Not enough data" : "資料不足";
  const acute =
    input.acuteLoad === null
      ? noData
      : input.acuteLoad === 0
        ? en ? "No training in the last 7 days" : "近 7 天沒有訓練"
        : en ? `Last 7 days · ${input.trainingDays7} training days` : `近 7 天 · ${input.trainingDays7} 天有訓練`;
  const chronic =
    input.chronicLoad === null || input.chronicLoad === 0
      ? noData
      : en ? "Last 28 days, weekly" : "近 28 天週均";
  const ratio =
    usableAcwr(input.loadRatio) === null ? noData : en ? "Last 7 days ÷ baseline" : "近 7 天 ÷ 基準";
  const weather =
    input.temperatureC === null ? (en ? "No weather data" : "暫無天候資料") : en ? "Where you are now" : "目前所在地";
  return { acute, chronic, ratio, weather };
}

/* ---------------- count-up ---------------- */

/** The number shown `progress` (0..1) of the way from `from` to `to`, easing
 *  out, rounded to `decimals`. Ends exactly on `to`. */
export function countUpValue(from: number, to: number, progress: number, decimals: number): number {
  if (from === to) return to;
  const t = Math.min(1, Math.max(0, progress));
  if (t >= 1) return to;
  const eased = 1 - Math.pow(1 - t, 3);
  const factor = 10 ** decimals;
  return Math.round((from + (to - from) * eased) * factor) / factor;
}

/* ---------------- 身體回報 ---------------- */

export interface InjuryDraft {
  bodyPart: string;
  severity: string;
  bonePain: boolean;
  chestPain: boolean;
  note: string;
}

export function injuryReady(injury: InjuryDraft): boolean {
  return injury.bodyPart !== "" && injury.severity !== "";
}

/** "膝蓋 (Knee)" reads "膝蓋" on screen. Display only: the submitted value
 *  keeps its original text. */
export function plainChoice(value: string): string {
  return value.replace(/\s*\([^)]*\)\s*$/, "") || value;
}

/** "膝蓋 (Knee)" reads "Knee" in English, "膝蓋" otherwise. Display only. */
export function choiceLabel(value: string, en: boolean): string {
  if (!en) return plainChoice(value);
  return value.match(/\(([^)]*)\)\s*$/)?.[1]?.trim() || value;
}

/** 部位・程度・警示徵兆 in one line. */
export function injurySummary(injury: InjuryDraft, en: boolean): string {
  const part = injury.bodyPart ? choiceLabel(injury.bodyPart, en) : en ? "No body part yet" : "尚未選擇部位";
  const level = injury.severity ? choiceLabel(injury.severity, en) : en ? "no severity yet" : "尚未選擇程度";
  const flags = injury.bonePain || injury.chestPain;
  const warn = en ? (flags ? "warning signs present" : "no warning signs") : flags ? "有警示徵兆" : "無警示徵兆";
  return `${part}・${level}・${warn}`;
}

/* ---------------- the proposal card ---------------- */

export interface PlanSize {
  minutes: number;
  km: number;
}

/** Proposed minus current. A distance difference is only meaningful when at
 *  least one side is a run. */
export function planDelta(
  current: PlanSize | null,
  proposed: PlanSize,
): { minutes: number | null; km: number | null } {
  if (!current) return { minutes: null, km: null };
  return {
    minutes: proposed.minutes - current.minutes,
    km: current.km <= 0 && proposed.km <= 0 ? null : proposed.km - current.km,
  };
}

/* ---------------- the coach's avatar ---------------- */

export type CoachAvatarSize = "sm" | "md" | "lg";

/** Pixel sizes: sm beside a message, md in a header (the persona avatars'
 *  36px), lg for the opening state. */
export const COACH_AVATAR_PX: Record<CoachAvatarSize, number> = { sm: 28, md: 36, lg: 64 };

/* ---------------- menus ---------------- */

/** Arrow keys, Home and End move through a menu's items and wrap. null when
 *  the key is not a navigation key. */
export function roveIndex(length: number, current: number, key: string): number | null {
  if (length <= 0) return null;
  if (key === "ArrowDown") return (current + 1) % length;
  if (key === "ArrowUp") return (current + length - 1) % length;
  if (key === "Home") return 0;
  if (key === "End") return length - 1;
  return null;
}

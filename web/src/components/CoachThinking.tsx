import { usableAcwr } from "../lib/acwr.ts";
import { CheckCircle } from "@phosphor-icons/react";
import { AnimatePresence, motion } from "framer-motion";
import type { ThinkingStep } from "../lib/coachConversation.ts";
import { CoachAvatar } from "./CoachAvatar.tsx";
import { MOTION, useMotion } from "./motion.tsx";

/** What the coach did to reach its answer, in the order it did it.
 *
 *  These are steps the server reported having completed, each with what it
 *  found, so the wording is past tense. The only thing still in progress is
 *  the answer itself.
 */
export function CoachThinking({
  steps,
  stillWorking,
  busy,
  en,
}: {
  steps: ThinkingStep[];
  stillWorking: boolean;
  /** thinking or streaming: the avatar's ring breathes until the answer is done */
  busy: boolean;
  en: boolean;
}) {
  const { pick } = useMotion();
  return (
    <div className="cc-coach-row cc-enter-coach" role="status">
    <CoachAvatar size="sm" state={busy ? "thinking" : "idle"} />
    <div className="cc-steps">
      <ul className="cc-steps-list">
        {steps.map((step, index) => (
          <li key={`${step.kind}-${index}`} className="cc-step cc-step--done">
            <CheckCircle size={16} weight="bold" aria-hidden="true" className="cc-step-icon" />
            <span>{describe(step, en)}</span>
          </li>
        ))}
      </ul>

      {/* The coach is here while it works. On the first word the mark
          leaves in --motion-press and the text caret takes over. */}
      <AnimatePresence initial={false}>
        {stillWorking && (
          <motion.div
            key="presence"
            className="cc-presence"
            exit={{ opacity: 0 }}
            transition={pick({ duration: MOTION.press })}
          >
            <span>{en ? "Working on it" : "正在整理"}</span>
            <span className="cc-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
    </div>
  );
}

function describe(step: ThinkingStep, en: boolean): string {
  switch (step.kind) {
    case "READ_TRAINING_LOAD":
      if (step.activityCount === 0) {
        return en
          ? "Looked at your recent training — no sessions recorded yet"
          : "看過你近期的訓練 — 目前還沒有紀錄";
      }
      return en
        ? `Reviewed ${step.activityCount} sessions across 28 days (${step.totalDistanceKm.toFixed(1)} km${
            usableAcwr(step.loadRatio) === null ? "" : `, ratio ${step.loadRatio!.toFixed(2)}`
          })`
        : `看過近 28 天的 ${step.activityCount} 次訓練（${step.totalDistanceKm.toFixed(1)} km${
            usableAcwr(step.loadRatio) === null ? "" : `，ACWR 負荷比 ${step.loadRatio!.toFixed(2)}`
          }）`;

    case "REVIEWED_GUIDANCE":
      if (step.count === 0) {
        return en
          ? "Checked the guidance library — nothing specific applied"
          : "查過指引資料 — 沒有特別相關的條目";
      }
      return en
        ? `Reviewed ${step.count} published guidance ${step.count === 1 ? "source" : "sources"}`
        : `參考了 ${step.count} 則已發表的專業指引`;

    case "CONSIDERED_OPTIONS":
      return en
        ? `Weighed ${step.count} options for you${
            step.personalised ? "" : " — using the conservative order for now"
          }`
        : `評估了 ${step.count} 個可行選項${step.personalised ? "" : " — 目前先採用保守排序"}`;
  }
}

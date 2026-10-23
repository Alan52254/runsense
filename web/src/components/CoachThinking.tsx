import { usableAcwr } from "../lib/acwr.ts";
import { CheckCircle, CircleNotch } from "@phosphor-icons/react";
import type { ThinkingStep } from "../lib/coachConversation.ts";

/** What the coach did to reach its answer, in the order it did it.
 *
 *  These are steps the server reported having completed, each with what it
 *  found, so the wording is past tense. The only thing still in progress is
 *  the answer itself.
 */
export function CoachThinking({
  steps,
  stillWorking,
  en,
}: {
  steps: ThinkingStep[];
  stillWorking: boolean;
  en: boolean;
}) {
  return (
    <div className="cc-steps" role="status">
      <ul className="cc-steps-list">
        {steps.map((step, index) => (
          <li key={`${step.kind}-${index}`} className="cc-step">
            <CheckCircle size={16} weight="bold" aria-hidden="true" className="cc-step-icon" />
            <span>{describe(step, en)}</span>
          </li>
        ))}
      </ul>

      {stillWorking && (
        <div className="cc-step cc-step--working">
          <CircleNotch size={16} weight="bold" aria-hidden="true" className="cc-spinner" />
          <span>{en ? "Working out what to suggest…" : "正在整理給你的建議…"}</span>
        </div>
      )}
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
        ? `Reviewed ${step.count} pieces of published guidance`
        : `參考了 ${step.count} 則已發表的專業指引`;

    case "CONSIDERED_OPTIONS":
      return en
        ? `Weighed ${step.count} options for you${
            step.personalised ? "" : " — using the conservative order for now"
          }`
        : `評估了 ${step.count} 個可行選項${step.personalised ? "" : " — 目前先採用保守排序"}`;
  }
}

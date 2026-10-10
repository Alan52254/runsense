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
    <div
      style={{
        alignSelf: "flex-start",
        maxWidth: "96%",
        padding: "12px 14px",
        borderRadius: "16px 16px 16px 4px",
        backgroundColor: "var(--surface-2)",
        border: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        gap: 7,
      }}
    >
      {steps.map((step, index) => (
        <div
          key={`${step.kind}-${index}`}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12.5,
            color: "var(--text-2)",
            animation: "fadeIn 0.25s ease-out both",
            animationDelay: `${index * 0.08}s`,
          }}
        >
          <CheckCircle size={15} weight="fill" color="var(--accent)" aria-hidden="true" />
          <span>{describe(step, en)}</span>
        </div>
      ))}

      {stillWorking && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12.5,
            fontWeight: 650,
            color: "var(--accent-ink)",
          }}
        >
          <CircleNotch
            size={15}
            weight="bold"
            aria-hidden="true"
            style={{ animation: "spin 0.9s linear infinite" }}
          />
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
            step.loadRatio === null ? "" : `, ratio ${step.loadRatio.toFixed(2)}`
          })`
        : `看過近 28 天的 ${step.activityCount} 次訓練（${step.totalDistanceKm.toFixed(1)} km${
            step.loadRatio === null ? "" : `，負荷比 ${step.loadRatio.toFixed(2)}`
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

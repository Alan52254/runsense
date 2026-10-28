import assert from "node:assert/strict";
import test from "node:test";
import type { CoachPhase, CoachProposal, Citation, ThinkingStep } from "./coachConversation.ts";
import {
  COACH_AVATAR_PX,
  countUpValue,
  figureSources,
  figuresUsedBy,
  followUpChips,
  injuryReady,
  injurySummary,
  lastUserMessage,
  planDelta,
  roveIndex,
  plainChoice,
  choiceLabel,
  litFigures,
  shouldEnterAnimated,
  shouldStickToBottom,
  tabDirection,
  headerShowsFace,
  startsAtTop,
  threadStage,
  undeliveredIndex,
} from "./coachChatUi.ts";

const citation: Citation = {
  evidenceId: "e1",
  title: "跑者膝痛",
  publisher: "BJSM",
  sourceUrl: "https://example.test",
  bodyParts: ["膝蓋"],
  phase: "acute",
};
const loadStep: ThinkingStep = {
  kind: "READ_TRAINING_LOAD",
  observationDays: 28,
  loadRatio: 1.1,
  activityCount: 9,
  recentActivityCount: 3,
  totalDistanceKm: 60,
};
const guidanceStep: ThinkingStep = { kind: "REVIEWED_GUIDANCE", count: 1, citations: [citation] };
const optionsStep: ThinkingStep = { kind: "CONSIDERED_OPTIONS", count: 3, personalised: true };

function proposal(over: Partial<CoachProposal["facts"]> = {}): CoachProposal {
  return {
    id: "p1",
    label: "",
    changedFacts: [],
    accepted: false,
    abstained: false,
    confidence: null,
    speedLossPct: null,
    pacingIsExtrapolated: false,
    coachAssigned: [],
    selfApplyAllowed: true,
    canSendToCoach: true,
    easyPace: null,
    facts: {
      localDate: "2026-10-24",
      temperatureC: null,
      humidityPct: null,
      availableMinutes: 30,
      reportedBodyPart: null,
      reportedSeverityBand: null,
      ...over,
    },
    candidates: [],
  };
}

function answered(steps: ThinkingStep[], p: CoachProposal | null = null): CoachPhase {
  return { kind: "answered", steps, text: "好的", proposal: p };
}

// ---- scrolling ----

test("the thread sticks to the bottom only while the reader is near it", () => {
  assert.equal(shouldStickToBottom(920, 400, 1320), true); // exactly at the end
  assert.equal(shouldStickToBottom(870, 400, 1320), true); // 50px short
  assert.equal(shouldStickToBottom(700, 400, 1320), false); // scrolled up
  assert.equal(shouldStickToBottom(0, 400, 380), true); // nothing to scroll
});

// ---- follow-up chips ----

test("follow-ups come from the answer's own facts, nothing else", () => {
  const chips = followUpChips(answered([loadStep, guidanceStep, optionsStep], proposal()), {
    en: false,
    today: "2026-10-24",
  });
  assert.deepEqual(
    chips.map((c) => c.label),
    ["把 30 分鐘版本排進今天", "看這份指引原文", "我近 28 天的 9 次訓練，下週該怎麼接？"],
  );
  assert.deepEqual(chips[0].action, { kind: "send", text: "把 30 分鐘版本排進今天" });
  assert.deepEqual(chips[1].action, { kind: "citation", citation });
});

test("no facts, no chips: nothing is invented", () => {
  assert.deepEqual(followUpChips(answered([optionsStep]), { en: false, today: "2026-10-24" }), []);
  assert.deepEqual(
    followUpChips(answered([{ ...loadStep, activityCount: 0 }]), { en: false, today: "2026-10-24" }),
    [],
  );
});

test("follow-ups appear only once the answer is complete", () => {
  const streaming: CoachPhase = { kind: "streaming", steps: [guidanceStep], text: "先" };
  assert.deepEqual(followUpChips(streaming, { en: false, today: "2026-10-24" }), []);
  assert.deepEqual(followUpChips({ kind: "failed", text: "x" }, { en: false, today: "2026-10-24" }), []);
});

test("a proposal for another day does not say today", () => {
  const chips = followUpChips(answered([], proposal({ localDate: "2026-11-02" })), {
    en: false,
    today: "2026-10-24",
  });
  assert.equal(chips[0].label, "把 30 分鐘版本排進 2026-11-02");
});

// ---- prompt row ----

test("the opening cards and the follow-ups never share the thread", () => {
  assert.deepEqual(threadStage({ hasUserMessage: false, phaseKind: "idle", hasFollowUps: false }), { openingCards: true, followUps: false });
  assert.deepEqual(threadStage({ hasUserMessage: true, phaseKind: "thinking", hasFollowUps: false }), { openingCards: false, followUps: false });
  assert.deepEqual(threadStage({ hasUserMessage: true, phaseKind: "answered", hasFollowUps: true }), { openingCards: false, followUps: true });
  // answered but nothing derivable: nothing is invented
  assert.deepEqual(threadStage({ hasUserMessage: true, phaseKind: "answered", hasFollowUps: false }), { openingCards: false, followUps: false });
});

test("the header's face waits while the opening shows its own", () => {
  const fresh = { hasUserMessage: false, phaseKind: "idle" as const };
  assert.equal(headerShowsFace({ tab: "chat", ...fresh }), false);
  assert.equal(headerShowsFace({ tab: "chat", hasUserMessage: true, phaseKind: "thinking" }), true);
  assert.equal(headerShowsFace({ tab: "chat", hasUserMessage: true, phaseKind: "answered" }), true);
  // other sections have no opening, so the face stays
  assert.equal(headerShowsFace({ tab: "injury", ...fresh }), true);
  assert.equal(headerShowsFace({ tab: "guidance", ...fresh }), true);
});

test("the chip lights for the figures the last finished step read", () => {
  assert.deepEqual([...litFigures({ kind: "idle" } as CoachPhase)], []);
  const phase = { kind: "thinking", steps: [loadStep] } as unknown as CoachPhase;
  assert.deepEqual([...litFigures(phase)].sort(), ["acute", "chronic", "ratio"]);
  const guidance = { kind: "thinking", steps: [loadStep, guidanceStep] } as unknown as CoachPhase;
  assert.equal(litFigures(guidance).size, 0);
});

// ---- count-up ----

test("count-up eases from the old value to the real one and ends exactly on it", () => {
  assert.equal(countUpValue(0, 100, 0, 0), 0);
  assert.equal(countUpValue(0, 100, 1, 0), 100);
  assert.equal(countUpValue(0, 100, 2, 0), 100); // clamped
  const mid = countUpValue(0, 100, 0.5, 0);
  assert.ok(mid > 50 && mid < 100, `ease-out is ahead of linear at half time, got ${mid}`);
  assert.equal(countUpValue(80, 20, 1, 0), 20);
  assert.equal(countUpValue(0, 1.31, 1, 2), 1.31);
  assert.ok((countUpValue(0, 1.31, 0.5, 2).toString().split(".")[1]?.length ?? 0) <= 2);
});

test("a figure that did not change does not move", () => {
  assert.equal(countUpValue(7, 7, 0.3, 0), 7);
});

// ---- the strip ----

test("only the figures a finished step really used light up", () => {
  assert.deepEqual(figuresUsedBy(loadStep), ["acute", "chronic", "ratio"]);
  assert.deepEqual(figuresUsedBy({ ...loadStep, loadRatio: null }), ["acute", "chronic"]);
  assert.deepEqual(figuresUsedBy({ ...loadStep, loadRatio: 0 }), ["acute", "chronic"]);
  assert.deepEqual(figuresUsedBy(guidanceStep), []);
  assert.deepEqual(figuresUsedBy(optionsStep), []);
});

test("zero load and a missing ratio are explained, not left as bare numbers", () => {
  const none = figureSources(
    { acuteLoad: 0, chronicLoad: 0, loadRatio: null, trainingDays7: 0, trainingDays28: 0, temperatureC: null },
    false,
  );
  assert.equal(none.acute, "近 7 天沒有訓練");
  assert.equal(none.chronic, "資料不足");
  assert.equal(none.ratio, "資料不足");
  assert.equal(none.weather, "暫無天候資料");

  const some = figureSources(
    { acuteLoad: 120, chronicLoad: 100, loadRatio: 1.2, trainingDays7: 3, trainingDays28: 11, temperatureC: 24 },
    false,
  );
  assert.equal(some.acute, "近 7 天 · 3 天有訓練");
  assert.equal(some.chronic, "近 28 天週均");
  assert.equal(some.ratio, "近 7 天 ÷ 基準");
  assert.equal(some.weather, "目前所在地");
});

// ---- composer ----

test("up-arrow recalls the last thing the Athlete said", () => {
  assert.equal(
    lastUserMessage([
      { role: "assistant", content: "你好" },
      { role: "user", content: "第一個" },
      { role: "assistant", content: "嗯" },
      { role: "user", content: "第二個" },
      { role: "assistant", content: "好" },
    ]),
    "第二個",
  );
  assert.equal(lastUserMessage([{ role: "assistant", content: "你好" }]), null);
});

test("existing messages are never re-animated", () => {
  assert.equal(shouldEnterAnimated(0, 3), false);
  assert.equal(shouldEnterAnimated(2, 3), false);
  assert.equal(shouldEnterAnimated(3, 3), true);
});

// ---- tabs ----

test("tabs slide in the direction of travel", () => {
  const order = ["chat", "injury", "guidance"] as const;
  assert.equal(tabDirection(order, "chat", "guidance"), "forward");
  assert.equal(tabDirection(order, "guidance", "injury"), "back");
  assert.equal(tabDirection(order, "chat", "chat"), "none");
});

// ---- 身體回報 ----

test("nothing is sendable until a body part and a severity are chosen", () => {
  const empty = { bodyPart: "", severity: "", bonePain: false, chestPain: false, note: "" };
  assert.equal(injuryReady(empty), false);
  assert.equal(injuryReady({ ...empty, bodyPart: "膝蓋 (Knee)" }), false);
  assert.equal(injuryReady({ ...empty, severity: "輕微 (Mild)" }), false);
  assert.equal(injuryReady({ ...empty, bodyPart: "膝蓋 (Knee)", severity: "輕微 (Mild)" }), true);
});

test("choices read in Chinese only on screen, and the data keeps its value", () => {
  assert.equal(plainChoice("膝蓋 (Knee)"), "膝蓋");
  assert.equal(plainChoice("小腿脛骨 (Shin Splints)"), "小腿脛骨");
  assert.equal(plainChoice("中度 (Moderate)"), "中度");
  assert.equal(plainChoice("Knee"), "Knee");
});

test("the summary names part, severity and warning signs", () => {
  const base = { bodyPart: "膝蓋 (Knee)", severity: "輕微 (Mild)", bonePain: false, chestPain: false, note: "" };
  assert.equal(injurySummary(base, false), "膝蓋・輕微・無警示徵兆");
  assert.equal(injurySummary({ ...base, bonePain: true }, false), "膝蓋・輕微・有警示徵兆");
  assert.equal(injurySummary({ ...base, bodyPart: "", severity: "" }, false), "尚未選擇部位・尚未選擇程度・無警示徵兆");
});

// ---- the proposal card ----

test("the plan delta is the proposed plan minus the current one", () => {
  assert.deepEqual(planDelta({ minutes: 50, km: 8 }, { minutes: 30, km: 5 }), { minutes: -20, km: -3 });
  assert.deepEqual(planDelta({ minutes: 30, km: 5 }, { minutes: 30, km: 5 }), { minutes: 0, km: 0 });
  assert.deepEqual(planDelta(null, { minutes: 30, km: 5 }), { minutes: null, km: null });
  assert.deepEqual(planDelta({ minutes: 45, km: 0 }, { minutes: 0, km: 0 }), { minutes: -45, km: null });
});

test("the coach avatar sizes step up and md matches the persona avatars", () => {
  assert.equal(COACH_AVATAR_PX.md, 36);
  assert.ok(COACH_AVATAR_PX.sm < COACH_AVATAR_PX.md && COACH_AVATAR_PX.md < COACH_AVATAR_PX.lg);
  assert.ok(COACH_AVATAR_PX.sm >= 24);
});

test("menu keys wrap around and ignore everything else", () => {
  assert.equal(roveIndex(3, 2, "ArrowDown"), 0);
  assert.equal(roveIndex(3, 0, "ArrowUp"), 2);
  assert.equal(roveIndex(3, 1, "Home"), 0);
  assert.equal(roveIndex(3, 1, "End"), 2);
  assert.equal(roveIndex(3, 1, "a"), null);
  assert.equal(roveIndex(0, 0, "ArrowDown"), null);
});

test("an untouched thread starts at its top so the opening is never scrolled under the header", () => {
  assert.equal(startsAtTop(0), true);
  assert.equal(startsAtTop(1), false);
});

test("a choice reads in the Athlete's language; the stored value is untouched", () => {
  assert.equal(choiceLabel("膝蓋 (Knee)", false), "膝蓋");
  assert.equal(choiceLabel("膝蓋 (Knee)", true), "Knee");
  assert.equal(choiceLabel("小腿脛骨 (Shin Splints)", true), "Shin Splints");
  assert.equal(choiceLabel("Knee", true), "Knee");
  assert.equal(choiceLabel("膝蓋", true), "膝蓋");
});

test("the summary line follows the language too", () => {
  const injury = { bodyPart: "膝蓋 (Knee)", severity: "輕微 (Mild)", bonePain: false, chestPain: false, note: "" };
  assert.equal(injurySummary(injury, true), "Knee・Mild・no warning signs");
});

test("only the question the coach never answered is marked as not delivered", () => {
  const messages = [
    { role: "assistant" as const, content: "你好" },
    { role: "user" as const, content: "今天練什麼？" },
  ];
  assert.equal(undeliveredIndex(messages, { kind: "failed", text: "x" }), 1);
  assert.equal(undeliveredIndex(messages, { kind: "thinking", steps: [] }), null);
  assert.equal(undeliveredIndex(messages, { kind: "idle" }), null);
  assert.equal(undeliveredIndex([messages[0]], { kind: "failed", text: "x" }), null);
});

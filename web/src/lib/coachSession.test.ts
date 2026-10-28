import assert from "node:assert/strict";
import test from "node:test";
import { createCoachSession } from "./coachSession.ts";
import type { CoachChatTransport } from "./coachSession.ts";
import { inMemoryCoachTransport } from "./coachChatTransport.memory.ts";

const welcome = { role: "assistant" as const, content: "你好" };

function session(transport: CoachChatTransport | null, en = false) {
  return createCoachSession({ transport: () => transport, english: () => en, welcome: [welcome] });
}

const proposal = {
  kind: "proposal" as const,
  proposal: {
    id: "p1",
    label: "輕鬆跑",
    candidates: [{ candidate_id: "c1", workout_type: "easy", duration_minutes: 30, distance_km: 5, running_allowed: true }],
  },
};

test("a second question while the coach is still answering is ignored", async () => {
  const transport = inMemoryCoachTransport({ replies: [[{ kind: "delta", delta: "慢慢跑" }]], hold: true });
  const coach = session(transport);

  const first = coach.send("今天練什麼？");
  const second = coach.send("還在嗎？");
  transport.release();
  await first;

  assert.notEqual(first, null);
  assert.equal(second, null);
  assert.equal(transport.sent.length, 1);
  assert.deepEqual(coach.getState().messages.map((m) => m.content), ["你好", "今天練什麼？"]);
});

test("a coach that cannot be reached answers with the unavailable text", async () => {
  const transport = inMemoryCoachTransport({ failStream: true });
  const coach = session(transport);

  await coach.send("今天練什麼？");

  assert.deepEqual(coach.getState().phase, {
    kind: "failed",
    text: "目前聯絡不上教練。你既有的課表與安全建議仍然有效；若有持續的急性疼痛，請諮詢專業醫師。",
  });
});

test("signed out, the question is kept and the coach is reported unavailable", async () => {
  const coach = session(null, true);

  await coach.send("What today?");

  assert.equal(coach.getState().messages.at(-1)?.content, "What today?");
  assert.equal(coach.getState().phase.kind, "failed");
});

test("a dropped stream keeps whatever text already arrived", async () => {
  const transport = inMemoryCoachTransport({ replies: [[{ kind: "delta", delta: "先休息" }]], failStream: true });
  const coach = session(transport);

  await coach.send("膝蓋痛");

  assert.equal(coach.getState().phase.kind, "answered");
  assert.equal(coach.getState().phase.kind === "answered" && coach.getState().phase.text, "先休息");
});

test("accepting a proposal applies it and refreshes the plan", async () => {
  const transport = inMemoryCoachTransport({ replies: [[{ kind: "delta", delta: "可以跑" }, proposal]] });
  const coach = session(transport);
  await coach.send("今天練什麼？");
  const state = coach.getState().phase;
  assert.ok(state.kind === "answered" && state.proposal);

  const outcome = await coach.acceptProposal(state.proposal);

  assert.equal(outcome, null);
  assert.deepEqual(transport.accepted, ["p1"]);
  assert.equal(transport.refreshes, 1);
  assert.equal(coach.getState().phase.kind === "answered" && coach.getState().phase.proposal, null);
});

test("a day the coach already scheduled is not applied and the plan is not refreshed", async () => {
  const transport = inMemoryCoachTransport({
    replies: [[{ kind: "delta", delta: "可以跑" }, proposal]],
    acceptOutcome: { applied: false, reason: "COACH_SCHEDULED" },
  });
  const coach = session(transport);
  await coach.send("今天練什麼？");
  const state = coach.getState().phase;
  assert.ok(state.kind === "answered" && state.proposal);

  const outcome = await coach.acceptProposal(state.proposal);

  assert.equal(outcome, "教練已經排了這天的課表，無法直接套用。可以把建議傳給教練討論。");
  assert.equal(transport.refreshes, 0);
});

test("the previous answer is folded into the transcript the coach sees next", async () => {
  const transport = inMemoryCoachTransport({
    replies: [[{ kind: "delta", delta: "跑 5 公里" }], [{ kind: "delta", delta: "好" }]],
  });
  const coach = session(transport);

  await coach.send("今天練什麼？");
  await coach.send("可以再短一點嗎？");

  assert.deepEqual(transport.sent[1].map((m) => m.content), ["你好", "今天練什麼？", "跑 5 公里", "可以再短一點嗎？"]);
});

test("a failed answer is not folded into the transcript", async () => {
  const transport = inMemoryCoachTransport({ failStream: true });
  const coach = session(transport);

  await coach.send("第一題");
  await coach.send("第二題");

  assert.deepEqual(coach.getState().messages.map((m) => m.content), ["你好", "第一題", "第二題"]);
});

test("a body report joins the conversation once", () => {
  const coach = session(inMemoryCoachTransport({}));
  const report = { bodyPart: "膝蓋", severityBand: "輕微", guidanceSummary: "休息兩天", nextSteps: ["冰敷"] };

  coach.addReport(report);
  coach.addReport(report);

  assert.deepEqual(coach.getState().messages.map((m) => m.content), ["你好", "你的最新評估結果：休息兩天\n冰敷"]);
});

/* retry after a failure */

function failThenAnswer() {
  let calls = 0;
  const sent: unknown[][] = [];
  const transport: CoachChatTransport = {
    async streamMessage(history, onEvent, onComplete) {
      calls += 1;
      sent.push(history);
      if (calls === 1) throw new Error("offline");
      onEvent({ kind: "delta", delta: "好的" });
      onComplete();
    },
    async acceptProposal() { return { applied: true }; },
    async dismissProposal() {},
    async shareProposal() {},
    async refreshPlan() {},
  };
  return { transport, sent, calls: () => calls };
}

test("retry sends the unanswered question again without adding a second copy of it", async () => {
  const { transport, sent } = failThenAnswer();
  const coach = session(transport);
  await coach.send("今天練什麼？");
  assert.equal(coach.getState().phase.kind, "failed");

  await coach.retry();

  assert.equal(coach.getState().phase.kind, "answered");
  assert.deepEqual(sent[1], sent[0]);
  assert.deepEqual(coach.getState().messages.map((m) => m.content), ["你好", "今天練什麼？"]);
});

test("retry while the coach is answering the retry is ignored, so it cannot double-send", async () => {
  let calls = 0;
  const transport = inMemoryCoachTransport({ failStream: true, hold: false });
  const coach = session(transport);
  await coach.send("今天練什麼？");
  const sentBefore = transport.sent.length;

  const first = coach.retry();
  const second = coach.retry();
  calls = transport.sent.length - sentBefore;
  await first;

  assert.notEqual(first, null);
  assert.equal(second, null);
  assert.equal(calls, 1);
  assert.equal(transport.sent.length, sentBefore + 1);
});

test("retry with nothing failed does nothing", async () => {
  const transport = inMemoryCoachTransport({ replies: [[{ kind: "delta", delta: "好" }]] });
  const coach = session(transport);
  assert.equal(coach.retry(), null);
  await coach.send("嗨");
  assert.equal(coach.retry(), null);
  assert.equal(transport.sent.length, 1);
});

test("retry that fails again stays failed and still holds one copy of the question", async () => {
  const transport = inMemoryCoachTransport({ failStream: true });
  const coach = session(transport);
  await coach.send("今天練什麼？");
  await coach.retry();
  assert.equal(coach.getState().phase.kind, "failed");
  assert.equal(coach.getState().messages.filter((m) => m.role === "user").length, 1);
  assert.equal(transport.sent.length, 2);
});

test("a send then a retry racing in the same tick sends once", async () => {
  const transport = inMemoryCoachTransport({ failStream: true, hold: true });
  const coach = session(transport);
  const asked = coach.send("今天練什麼？");
  assert.equal(coach.retry(), null);
  transport.release();
  await asked;
  assert.equal(transport.sent.length, 1);
});

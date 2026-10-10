import assert from "node:assert/strict";
import test from "node:test";
import {
  IDLE,
  coachPhaseReducer,
  isBusy,
  pendingProposal,
  visibleText,
} from "./coachConversation.ts";
import type { CoachEvent, CoachPhase, CoachProposal } from "./coachConversation.ts";

function proposal(overrides: Partial<CoachProposal> = {}): CoachProposal {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    label: "Short session today",
    changedFacts: ["available_minutes"],
    accepted: false,
    abstained: false,
    confidence: 0.62,
    speedLossPct: 2.4,
    pacingIsExtrapolated: false,
    coachAssigned: [],
    selfApplyAllowed: true,
    facts: {
      localDate: "2026-08-30",
      temperatureC: 28,
      humidityPct: 75,
      availableMinutes: 30,
      reportedBodyPart: null,
      reportedSeverityBand: null,
    },
    candidates: [
      {
        candidateId: "recovery-run",
        workoutType: "RECOVERY_RUN",
        durationMinutes: 20,
        distanceKm: 3,
        runningAllowed: true,
      },
    ],
    ...overrides,
  };
}

function run(events: CoachEvent[], from: CoachPhase = IDLE): CoachPhase {
  return events.reduce(coachPhaseReducer, from);
}

test("a question moves the coach into thinking", () => {
  assert.deepEqual(run([{ type: "ASKED" }]), { kind: "thinking", steps: [] });
});

test("steps accumulate in the order they were reported", () => {
  const phase = run([
    { type: "ASKED" },
    { type: "STEP", step: { kind: "READ_TRAINING_LOAD", observationDays: 20, loadRatio: 1.14 } },
    { type: "STEP", step: { kind: "REVIEWED_GUIDANCE", count: 4, citations: [] } },
  ]);

  assert.equal(phase.kind, "thinking");
  assert.deepEqual(
    phase.kind === "thinking" ? phase.steps.map((s) => s.kind) : [],
    ["READ_TRAINING_LOAD", "REVIEWED_GUIDANCE"],
  );
});

test("the first token moves the coach from thinking to streaming", () => {
  const phase = run([{ type: "ASKED" }, { type: "DELTA", delta: "你" }]);

  assert.equal(phase.kind, "streaming");
  assert.equal(visibleText(phase), "你");
});

test("thinking and streaming are never both true", () => {
  const phase = run([
    { type: "ASKED" },
    { type: "STEP", step: { kind: "REVIEWED_GUIDANCE", count: 2, citations: [] } },
    { type: "DELTA", delta: "好" },
  ]);

  // A single value cannot be in two states -- this is the point of the union.
  assert.equal(phase.kind, "streaming");
});

test("steps survive the move into streaming", () => {
  const phase = run([
    { type: "ASKED" },
    { type: "STEP", step: { kind: "REVIEWED_GUIDANCE", count: 4, citations: [] } },
    { type: "DELTA", delta: "好" },
  ]);

  assert.deepEqual(phase.kind === "streaming" ? phase.steps.length : 0, 1);
});

test("deltas accumulate into one answer", () => {
  const phase = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "今天" },
    { type: "DELTA", delta: "建議" },
    { type: "DELTA", delta: "輕鬆跑" },
  ]);

  assert.equal(visibleText(phase), "今天建議輕鬆跑");
});

test("a proposal arrives alongside the answer, not instead of it", () => {
  const phase = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "考量你只有 30 分鐘" },
    { type: "PROPOSED", proposal: proposal() },
  ]);

  assert.equal(phase.kind, "proposal");
  assert.equal(visibleText(phase), "考量你只有 30 分鐘");
});

test("a proposal is not accepted when it arrives", () => {
  const phase = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "…" },
    { type: "PROPOSED", proposal: proposal() },
  ]);

  assert.equal(phase.kind === "proposal" ? phase.proposal.accepted : true, false);
});

test("dismissing a proposal leaves the answer and changes nothing else", () => {
  const withProposal = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "建議如下" },
    { type: "PROPOSED", proposal: proposal() },
  ]);

  const after = coachPhaseReducer(withProposal, { type: "PROPOSAL_DISMISSED" });

  assert.equal(after.kind, "answered");
  assert.equal(visibleText(after), "建議如下");
  assert.equal(pendingProposal(after), null);
  // Declining must not leave the Athlete unable to ask anything else.
  assert.equal(isBusy(after), false);
});

test("accepting a proposal also clears it from the conversation", () => {
  const withProposal = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "建議如下" },
    { type: "PROPOSED", proposal: proposal() },
  ]);

  const after = coachPhaseReducer(withProposal, { type: "PROPOSAL_ACCEPTED" });

  assert.equal(after.kind, "answered");
  assert.equal(pendingProposal(after), null);
  assert.equal(isBusy(after), false);
});

test("a stream that produced nothing settles back to idle rather than an empty answer", () => {
  assert.deepEqual(run([{ type: "ASKED" }, { type: "SETTLED" }]), IDLE);
});

test("the Athlete can ask a second question once the first answer is complete", () => {
  const settled = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "第一個回答" },
    { type: "SETTLED" },
  ]);

  assert.equal(isBusy(settled), false);
  assert.equal(visibleText(settled), "第一個回答");
});

test("a settled answer keeps its proposal awaiting a decision", () => {
  const settled = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "建議如下" },
    { type: "PROPOSED", proposal: proposal() },
    { type: "SETTLED" },
  ]);

  assert.equal(isBusy(settled), false);
  assert.equal(pendingProposal(settled)?.label, "Short session today");
});

test("dismissing a settled proposal leaves the answer and no proposal", () => {
  const settled = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "建議如下" },
    { type: "PROPOSED", proposal: proposal() },
    { type: "SETTLED" },
    { type: "PROPOSAL_DISMISSED" },
  ]);

  assert.equal(pendingProposal(settled), null);
  assert.equal(visibleText(settled), "建議如下");
});

test("a late token cannot reopen a settled answer", () => {
  const settled = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "完成" },
    { type: "SETTLED" },
    { type: "DELTA", delta: "遲到的字" },
  ]);

  assert.equal(visibleText(settled), "完成");
  assert.equal(isBusy(settled), false);
});

test("asking again starts a fresh turn", () => {
  const settled = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "第一個回答" },
    { type: "SETTLED" },
  ]);

  assert.deepEqual(coachPhaseReducer(settled, { type: "ASKED" }), {
    kind: "thinking",
    steps: [],
  });
});

test("a failure replaces the phase with a message the Athlete can read", () => {
  const phase = run([
    { type: "ASKED" },
    { type: "DELTA", delta: "部分" },
    { type: "FAILED", text: "教練目前無法回覆" },
  ]);

  assert.equal(phase.kind, "failed");
  assert.equal(visibleText(phase), "教練目前無法回覆");
});

test("nothing arrives after a failure", () => {
  const failed = run([{ type: "ASKED" }, { type: "FAILED", text: "無法回覆" }]);

  assert.equal(coachPhaseReducer(failed, { type: "DELTA", delta: "x" }).kind, "failed");
  assert.equal(
    coachPhaseReducer(failed, { type: "PROPOSED", proposal: proposal() }).kind,
    "failed",
  );
});

test("a stray token outside a conversation is ignored", () => {
  assert.equal(coachPhaseReducer(IDLE, { type: "DELTA", delta: "x" }).kind, "idle");
});

test("a proposal cannot appear without a conversation", () => {
  assert.equal(
    coachPhaseReducer(IDLE, { type: "PROPOSED", proposal: proposal() }).kind,
    "idle",
  );
});

test("the Athlete is blocked from asking again only while the coach is working", () => {
  assert.equal(isBusy(IDLE), false);
  assert.equal(isBusy(run([{ type: "ASKED" }])), true);
  assert.equal(isBusy(run([{ type: "ASKED" }, { type: "DELTA", delta: "x" }])), true);
  assert.equal(
    isBusy(
      run([
        { type: "ASKED" },
        { type: "DELTA", delta: "x" },
        { type: "PROPOSED", proposal: proposal() },
      ]),
    ),
    false,
  );
  assert.equal(isBusy(run([{ type: "ASKED" }, { type: "FAILED", text: "x" }])), false);
});

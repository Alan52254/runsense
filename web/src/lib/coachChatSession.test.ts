import assert from "node:assert/strict";
import test from "node:test";
import { appendOnce, reportContextMessage, wrapFocusIndex } from "./coachChatSession.ts";

test("a report opened twice adds its message to the conversation once", () => {
  const welcome = { role: "assistant" as const, content: "你好" };
  const report = { role: "assistant" as const, content: "你的最新評估結果：休息兩天" };

  const once = appendOnce([welcome], report);
  const twice = appendOnce(once, report);

  assert.deepEqual(twice, [welcome, report]);
  assert.equal(twice, once, "unchanged conversation keeps its identity");
});

test("a body report becomes one coach message with its summary and next steps", () => {
  const ctx = {
    bodyPart: "膝蓋 (Knee)",
    severityBand: "MILD",
    guidanceSummary: "輕微不適，可以減量。",
    nextSteps: ["今天改輕鬆跑", "冰敷 15 分鐘"],
  };

  assert.equal(
    reportContextMessage(ctx, false),
    "你的最新評估結果：輕微不適，可以減量。\n今天改輕鬆跑\n冰敷 15 分鐘",
  );
  assert.equal(
    reportContextMessage(ctx, true),
    "Your latest assessment: 輕微不適，可以減量。\n今天改輕鬆跑\n冰敷 15 分鐘",
  );
});

test("Tab wraps at the drawer's edges and is left alone in between", () => {
  // five focusable controls in the drawer
  assert.equal(wrapFocusIndex(5, 4, false), 0, "Tab on the last goes to the first");
  assert.equal(wrapFocusIndex(5, 0, true), 4, "Shift+Tab on the first goes to the last");
  assert.equal(wrapFocusIndex(5, 2, false), null, "inside: the browser moves focus");
  assert.equal(wrapFocusIndex(5, 2, true), null);
  assert.equal(wrapFocusIndex(5, -1, false), 0, "focus outside the drawer is pulled in");
  assert.equal(wrapFocusIndex(5, -1, true), 4);
  assert.equal(wrapFocusIndex(0, -1, false), null, "nothing to focus");
});

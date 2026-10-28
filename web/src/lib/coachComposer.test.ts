import assert from "node:assert/strict";
import test from "node:test";
import { COMPOSER_MAX_PX, COMPOSER_MIN_PX, canSend, composerHeight, composerHint, composerKeyAction } from "./coachComposer.ts";

const base = { key: "", shiftKey: false, composing: false, input: "", lastUserMessage: null };

test("Enter sends, Shift+Enter breaks the line", () => {
  assert.deepEqual(composerKeyAction({ ...base, key: "Enter", input: "hi" }), { kind: "send" });
  assert.deepEqual(composerKeyAction({ ...base, key: "Enter", shiftKey: true, input: "hi" }), { kind: "none" });
});

test("a word being confirmed by an IME is never a send", () => {
  assert.deepEqual(composerKeyAction({ ...base, key: "Enter", composing: true, input: "ni" }), { kind: "none" });
});

test("ArrowUp recalls the last message only into an empty box", () => {
  assert.deepEqual(composerKeyAction({ ...base, key: "ArrowUp", lastUserMessage: "我今天只有 30 分鐘。" }), { kind: "recall", text: "我今天只有 30 分鐘。" });
  assert.deepEqual(composerKeyAction({ ...base, key: "ArrowUp", input: "x", lastUserMessage: "a" }), { kind: "none" });
  assert.deepEqual(composerKeyAction({ ...base, key: "ArrowUp" }), { kind: "none" });
});

test("sending needs words and an idle coach; typing never waits", () => {
  assert.equal(canSend("  ", false), false);
  assert.equal(canSend("hi", true), false);
  assert.equal(canSend("hi", false), true);
  assert.equal(composerHint(true), "busy");
  assert.equal(composerHint(false), "ask");
});

test("the box grows to a cap and an empty box is one line", () => {
  assert.equal(composerHeight(500, true), COMPOSER_MIN_PX);
  assert.equal(composerHeight(60, false), 60);
  assert.equal(composerHeight(900, false), COMPOSER_MAX_PX);
  assert.equal(composerHeight(10, false), COMPOSER_MIN_PX);
});

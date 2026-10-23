import assert from "node:assert/strict";
import test from "node:test";

import { climateMomentLabel, paceShiftText } from "./climateShift.ts";
import { applyPctToPace } from "./paceCalc.ts";

test("a positive speed loss is slower, and says so", () => {
  assert.equal(paceShiftText(0.8, "zh-TW"), "慢 0.8%");
  assert.equal(paceShiftText(0.8, "en"), "0.8% slower");
  // the pace moves the same way the words do
  assert.ok(applyPctToPace(360, 0.8) > 360);
});

test("a negative speed loss is faster, never '+-0.8%' or a bare '-0.8%'", () => {
  assert.equal(paceShiftText(-0.8, "zh-TW"), "快 0.8%");
  assert.equal(paceShiftText(-0.8, "en"), "0.8% faster");
  assert.ok(applyPctToPace(360, -0.8) < 360);
});

test("a shift that rounds to zero reads as no change, not '+0.0%'", () => {
  assert.equal(paceShiftText(0.04, "zh-TW"), "不受影響");
  assert.equal(paceShiftText(-0.04, "en"), "no change");
  assert.equal(paceShiftText(0, "zh-TW"), "不受影響");
});

test("now and a time slot are named apart", () => {
  assert.equal(climateMomentLabel(null, "zh-TW"), "現在");
  assert.equal(climateMomentLabel("evening", "zh-TW"), "18:30 時段");
  assert.equal(climateMomentLabel("morning", "zh-TW"), "06:00 時段");
  assert.equal(climateMomentLabel("evening", "en"), "18:30 slot");
  assert.equal(climateMomentLabel(null, "en"), "now");
});

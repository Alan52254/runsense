import assert from "node:assert/strict";
import test from "node:test";

import { formatDuration } from "./format.ts";

test("formats fractional Garmin minutes without exposing raw decimals", () => {
  assert.equal(formatDuration(37.924, "en"), "38 min");
  assert.equal(formatDuration(62.638, "en"), "1 hr 3 min");
  assert.equal(formatDuration(62.638, "zh-TW"), "1 小時 3 分");
});

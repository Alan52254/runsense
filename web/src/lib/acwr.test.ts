import assert from "node:assert/strict";
import test from "node:test";

import { acwrChipText, acwrValueText, acwrZoneLabel, deriveAcwrZone, normalizeLoadWording, usableAcwr } from "./acwr.ts";

test("zones split at 0.8, 1.3 and 1.5", () => {
  assert.equal(deriveAcwrZone(null), null);
  assert.equal(deriveAcwrZone(0.79), "low");
  assert.equal(deriveAcwrZone(0.8), "safe");
  assert.equal(deriveAcwrZone(1.3), "safe");
  assert.equal(deriveAcwrZone(1.5), "high");
  assert.equal(deriveAcwrZone(1.51), "alert");
});

test("the chip names the ratio once and uses the shared zone words", () => {
  assert.equal(acwrChipText(0.11, "zh-TW"), "ACWR 0.11 · 低於安全區間");
  assert.equal(acwrChipText(null, "zh-TW"), "ACWR 資料不足");
  assert.equal(acwrZoneLabel("safe", "en"), "in safe range");
});

test("older server wording is rewritten into the same vocabulary", () => {
  assert.equal(normalizeLoadWording("近期負荷偏低，可加入適度刺激"), "ACWR 負荷比低於安全區間，可加入適度刺激");
});

test("a ratio of 0 means no acute load yet: 資料不足, never 0.00", () => {
  assert.equal(usableAcwr(0), null);
  assert.equal(usableAcwr(null), null);
  assert.equal(usableAcwr(0.74), 0.74);
  assert.equal(deriveAcwrZone(0), null);
  assert.equal(acwrValueText(0, "zh-TW"), "資料不足");
  assert.equal(acwrValueText(null, "en"), "insufficient data");
  assert.equal(acwrValueText(0.74, "zh-TW"), "0.74");
  assert.equal(acwrChipText(0, "zh-TW"), "ACWR 資料不足");
});

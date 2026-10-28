import assert from "node:assert/strict";
import test from "node:test";
import { openingPrompts } from "./coachPrompts.ts";

const bare = { en: false, loadRatio: "—", temperatureC: null, humidityPct: null, report: null };

test("four cards, each naming where it draws from", () => {
  const cards = openingPrompts(bare);
  assert.equal(cards.length, 4);
  assert.ok(cards.every((card) => card.prompt && card.source));
});

test("a missing figure is left out of the question, never invented", () => {
  const [load, weather] = openingPrompts(bare);
  assert.doesNotMatch(load.prompt, /\d/);
  assert.doesNotMatch(weather.prompt, /°C/);
});

test("real figures appear in the question", () => {
  const [load, weather, , report] = openingPrompts({
    ...bare,
    loadRatio: "1.12",
    temperatureC: 14.6,
    humidityPct: 97,
    report: { bodyPart: "膝蓋", severityBand: "輕微" },
  });
  assert.match(load.prompt, /1\.12/);
  assert.match(weather.prompt, /15°C.*97%/);
  assert.match(report.prompt, /膝蓋（輕微）/);
});

test("the third card is the 30-minute question", () => {
  assert.equal(openingPrompts(bare)[2].prompt, "我今天只有 30 分鐘。");
});

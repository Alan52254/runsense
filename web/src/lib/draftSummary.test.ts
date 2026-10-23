import assert from "node:assert/strict";
import test from "node:test";

import type { PlanCardPayload, PlanPreviewWire } from "../data/apiClient.ts";
import { draftDateLabel, slotFrom, summarizeDraftWeek } from "./draftSummary.ts";

const block = { reps: 1, distance_m: 7000, duration_s: null, target_s_per_km: 355, target_mode: "exact" as const,
  target_text: "5:45-6:05/km", rest_s: null, rest_after_s: null };

function day(key: string, date: string, removed = false) {
  return { key, date, date_hint: "", source: "建議傍晚 18:00 跑（預報 12.8°C）\n目標配速 5:45-6:05/km", items: [{ type: "run" as const, title: "輕鬆跑" }],
    problems: [], removed };
}

function entry(on: string, before: number, after: number) {
  return { athlete_id: "a", name: "倫敦選手", status: "new" as const, load_consent: true,
    projected_load: { before, after, on, basis: "rpe" },
    items: [{ title: "輕鬆跑", summary: null, missing_variant: false, blocks: [block],
      record: { title: "輕鬆跑", duration_minutes: 40, intensity_label: "輕鬆跑", structure: [], tracked: true, notes: null } }] };
}

const payload = {
  plan: { days: [day("d1", "2026-10-27"), day("d2", "2026-10-28"), day("d3", "2026-10-29", true)] },
  athletes: [], source_text: "", today: "2026-10-23",
  schedule_draft: { version: 4, horizon: ["2026-10-23", "2026-10-29"], captured_at: "", inputs: {
    training_load: true, injury: false, weather: "forecast", health_coach: false, analysis: false, assignments: 0 },
    week: [{ date: "2026-10-28", label: "10/28", action: "add", current: [], proposed_text: null,
      weather_note: "建議早上 06:00 跑（預報 9.7°C）", reasons: [] }] },
} as unknown as PlanCardPayload;

const preview: PlanPreviewWire = { rows: [
  { key: "d1", date: "2026-10-27", entries: [entry("2026-10-29", 0, 0.45)] },
  { key: "d2", date: "2026-10-28", entries: [entry("2026-10-30", 0, 0.67)] },
  { key: "d3", date: "2026-10-29", entries: [entry("2026-10-31", 0, 0.9)] },
] };

test("the week summary counts kept days, main-set km and ACWR before -> after", () => {
  const s = summarizeDraftWeek(payload, preview);
  assert.equal(s.dayCount, 2);
  assert.equal(s.totalKm, 14);
  assert.equal(s.acwrBefore, 0);
  assert.equal(s.acwrAfter, 0.67);
});

test("each day reads date · type · distance @ pace · slot", () => {
  const [first, second] = summarizeDraftWeek(payload, preview).days;
  assert.equal(first.dateLabel, "10/27 週二");
  assert.equal(first.type, "輕鬆跑");
  assert.equal(first.distancePace, "7 km @ 5:55 /km");
  assert.equal(first.slot, "傍晚 18:00");
  assert.equal(second.slot, "早上 06:00");
});

test("labels degrade instead of inventing values", () => {
  assert.equal(draftDateLabel(null), "未定日期");
  assert.equal(slotFrom("目標配速 5:45/km"), null);
  assert.deepEqual(summarizeDraftWeek(payload, null).days[0].distancePace, null);
});

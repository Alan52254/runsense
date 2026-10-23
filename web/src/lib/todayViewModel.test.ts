import assert from "node:assert/strict";
import test from "node:test";

import { deriveAcwrZone, deriveTodayViewModel, resolveTimeOfDaySlot } from "./todayViewModel.ts";
import type { TodayInput } from "./todayViewModel.ts";
import type { GuidanceWireResponse, TrainingPlanWireResponse } from "../data/apiClient.ts";

const slots = [
  { label: "morning" as const, hour: 6, temperatureC: 14, speedLossPct: -1 },
  { label: "midday" as const, hour: 12, temperatureC: 22, speedLossPct: 2 },
  { label: "evening" as const, hour: 18.5, temperatureC: 18, speedLossPct: 0 },
];

test("the slot nearest the planned hour is chosen", () => {
  assert.equal(resolveTimeOfDaySlot(slots, 7.5)?.label, "morning");
  assert.equal(resolveTimeOfDaySlot(slots, 13)?.label, "midday");
  assert.equal(resolveTimeOfDaySlot(slots, 17)?.label, "evening");
});

test("slot distance wraps around midnight", () => {
  // 01:00 is 5h from 06:00 but only 6.5h from 18:30 the long way round,
  // and 23:30 is 5h from 18:30 but 6.5h from 06:00 across midnight.
  assert.equal(resolveTimeOfDaySlot(slots, 1)?.label, "morning");
  assert.equal(resolveTimeOfDaySlot(slots, 23.5)?.label, "evening");
  assert.equal(resolveTimeOfDaySlot([slots[0]!, slots[1]!], 23)?.label, "morning");
});

test("no slots means no slot", () => {
  assert.equal(resolveTimeOfDaySlot([], 9), null);
});

test("ACWR zones follow the 0.8 / 1.3 / 1.5 bands, inclusive at the top of each", () => {
  assert.equal(deriveAcwrZone(null), null);
  assert.equal(deriveAcwrZone(0.11), "low");
  assert.equal(deriveAcwrZone(0.79), "low");
  assert.equal(deriveAcwrZone(0.8), "safe");
  assert.equal(deriveAcwrZone(1.3), "safe");
  assert.equal(deriveAcwrZone(1.31), "high");
  assert.equal(deriveAcwrZone(1.5), "high");
  assert.equal(deriveAcwrZone(1.51), "alert");
});

const offlineWeather = {
  state: "LIVE" as const,
  city: "Tokyo",
  temperatureC: 18,
  humidityPct: 70,
  observedAtUtc: null,
  speedLossPct: 1,
  speedLossPctUnadjusted: 1,
  speedLossPctRelativeToNormal: 2,
  climateNormalTemperatureC: 17,
  climateNormalReferenceC: 17,
  timeOfDayEstimates: slots,
};

const guidance: GuidanceWireResponse = {
  local_date: "2026-10-23",
  recommendation: {
    workout_type: "節奏跑",
    duration_minutes: 45,
    distance_km: 8.7,
    target_pace_sec_per_km: 300,
    intensity_label: "RPE 6-7",
    adjustment_reason_code: "RECENT_LOAD_REDUCED",
    algorithm_version: "guidance-rule-2026.08.1",
    segments: [
      { id: "main", kind: "work", label: "節奏跑", distance_meters: null, duration_seconds: 1200, repetitions: null,
        target_pace_sec_per_km: null, target_pace_range_sec_per_km: [240, 270], after_repetition: null },
    ],
  },
  tone_variant_id: "NEUTRAL_FALLBACK",
  tone_text: "以下是今天的課表。",
  tone_reviewed_by: "x",
  computed_at: "2026-10-23T00:00:00Z",
};

function input(over: Partial<TodayInput> = {}): TodayInput {
  return {
    locale: "zh-TW",
    apiConfigured: true,
    plan: null,
    selectedCandidateId: null,
    guidance,
    offlineRecommendation: {
      id: "offline", localDate: "2026-10-23", workoutType: "輕鬆跑", durationMinutes: 30, distanceKm: 5,
      targetPaceSecPerKm: 360, intensityLabel: "easy", adjustmentReasonCode: "X", algorithmVersion: "v", segments: [],
    },
    liveWeather: null,
    offlineWeather,
    loadRatio: 1.0,
    ...over,
  };
}

const atSix = new Date(2026, 9, 23, 6, 0);
const atSevenPm = new Date(2026, 9, 23, 19, 0);

test("server pace makes the plan READY and the hero pace follows the active time slot", () => {
  const vm = deriveTodayViewModel(input(), atSevenPm);
  assert.equal(vm.planStatus, "READY");
  assert.equal(vm.workout.title, "節奏跑");
  assert.equal(vm.workout.targetPaceSecPerKm, 300);
  // Now: +2% speed loss vs normal -> 300 / 0.98.
  assert.equal(Math.round(vm.climate.nowPace.single!), 306);
  assert.equal(vm.climate.paceAdjustmentSec, 6);
  // 19:00 is nearest the 18:30 slot, which is at the evening normal (0%).
  assert.equal(vm.climate.activeSlot?.label, "evening");
  assert.equal(vm.climate.heroPace.single, 300);
  // 06:00 sits in the cool morning slot: a 1% bonus -> 300 / 1.01.
  assert.equal(Math.round(deriveTodayViewModel(input(), atSix).climate.heroPace.single!), 297);
});

test("the hero's climate figure is the active slot's own, so its sign matches its pace", () => {
  // Now is 2% slower than normal, but the hero shows the 18:30 slot.
  const tokyo = {
    ...offlineWeather,
    speedLossPctRelativeToNormal: -0.8,
    timeOfDayEstimates: [{ label: "evening" as const, hour: 18.5, temperatureC: 19, speedLossPct: 0.3 }],
  };
  const vm = deriveTodayViewModel(input({ offlineWeather: tokyo, apiConfigured: false }), atSevenPm);
  assert.equal(vm.climate.speedLossPct, -0.8);
  assert.equal(vm.climate.heroSlot, "evening");
  assert.equal(vm.climate.heroPct, 0.3);
  assert.ok(vm.climate.heroPace.single! > vm.workout.targetPaceSecPerKm!);
  // no slots: the hero is now, with now's figure
  const noSlots = deriveTodayViewModel(input({ offlineWeather: { ...tokyo, timeOfDayEstimates: [] }, apiConfigured: false }), atSevenPm);
  assert.equal(noSlots.climate.heroSlot, null);
  assert.equal(noSlots.climate.heroPct, -0.8);
  assert.ok(noSlots.climate.heroPace.single! < noSlots.workout.targetPaceSecPerKm!);
});

test("without a point pace the main-effort range is adjusted instead", () => {
  const noPoint = { ...guidance, recommendation: { ...guidance.recommendation, target_pace_sec_per_km: null } };
  const vm = deriveTodayViewModel(input({ guidance: noPoint }), atSix);
  assert.equal(vm.planStatus, "READY");
  assert.equal(vm.climate.heroPace.single, null);
  assert.deepEqual(vm.climate.heroPace.range?.map(Math.round), [238, 267]);
});

type WireCandidate = TrainingPlanWireResponse["candidates"][number];

function candidate(id: string, workout_type: WireCandidate["workout_type"], duration_minutes: number, distance_km: number, score: number): WireCandidate {
  return { candidate_id: id, workout_type, duration_minutes, distance_km, running_allowed: true, provenance_rule_ids: [], score, rationale: ["近期負荷偏低，可加入適度刺激"] };
}

function seg(kind: "warmup" | "work" | "cooldown", seconds: number, range: [number, number], meters: number | null = null) {
  return { id: kind, kind, label: kind, duration_seconds: seconds, distance_meters: meters, target_pace_sec_per_km: null, target_pace_range_sec_per_km: range };
}

function paced(c: WireCandidate, source: "athlete_history" | "rule_default", range: [number, number], mainSeconds: number, mainMeters: number): WireCandidate {
  return {
    ...c,
    pace_source: source,
    target_pace_s_per_km: Math.round((range[0] + range[1]) / 2),
    target_pace_range_s_per_km: range,
    segments: [seg("warmup", 300, [350, 375]), seg("work", mainSeconds, range, mainMeters), seg("cooldown", 300, [350, 375])],
  };
}

/* Tokyo 2026-10-23, as GET /training-plan/today returns it: four ranked
 * candidates, each run carrying the server's pace from Tokyo's easy runs. */
const tokyoPlan: TrainingPlanWireResponse = {
  local_date: "2026-10-23",
  ranker_version: "deterministic-plan-ranker-v2",
  abstained: false,
  abstention_reason: null,
  confidence: 0.35,
  reason_code: "LOAD_REDUCED_ADD_STIMULUS",
  inputs: { acute_load: 124.57, chronic_load: 1120.83, acute_chronic_ratio: 0.11, observation_days: 28, temperature_c: 18.2, weather_state: "CACHED", triage_urgency: null },
  feature_coverage: { training_load: true, weather: true, injury_triage: false },
  candidates: [
    paced(candidate("easy-run", "EASY_RUN", 40, 7, 0.84), "athlete_history", [330, 350], 1800, 6000),
    paced(candidate("steady-run", "STEADY_RUN", 45, 9, 0.84), "athlete_history", [310, 325], 1800, 7000),
    paced(candidate("recovery-run", "RECOVERY_RUN", 20, 3, 0.52), "athlete_history", [350, 375], 600, 2000),
    { ...candidate("rest-day", "REST_DAY", 0, 0, 0.2), pace_source: null, target_pace_s_per_km: null, target_pace_range_s_per_km: null, segments: [] },
  ],
};

test("a ranked candidate with the server's pace is READY and shows that pace and its segments", () => {
  const vm = deriveTodayViewModel(input({ plan: tokyoPlan }), atSevenPm);
  assert.equal(vm.planStatus, "READY");
  assert.equal(vm.paceSource, "server");
  assert.equal(vm.activeCandidateId, "easy-run");
  assert.equal(vm.workout.title, "輕鬆跑");
  assert.equal(vm.workout.durationMinutes, 40);
  assert.equal(vm.workout.distanceKm, 7);
  assert.equal(vm.workout.targetPaceSecPerKm, 340);
  assert.deepEqual(vm.workout.segments.map((s) => [s.kind, s.durationSeconds, s.targetPaceRangeSecPerKm]), [
    ["warmup", 300, [350, 375]], ["work", 1800, [330, 350]], ["cooldown", 300, [350, 375]],
  ]);
  assert.equal(vm.workout.segments[1]!.distanceMeters, 6000);
});

test("choosing another candidate switches the workout and the rest day needs no pace", () => {
  const steady = deriveTodayViewModel(input({ plan: tokyoPlan, selectedCandidateId: "steady-run" }), atSevenPm);
  assert.equal(steady.workout.title, "節奏/穩定跑");
  assert.equal(steady.workout.targetPaceSecPerKm, 318);
  assert.deepEqual(steady.ranking.map((r) => [r.id, r.isSelected]), [
    ["easy-run", false], ["steady-run", true], ["recovery-run", false], ["rest-day", false],
  ]);

  const rest = deriveTodayViewModel(input({ plan: tokyoPlan, selectedCandidateId: "rest-day" }), atSevenPm);
  assert.equal(rest.isRestDay, true);
  assert.equal(rest.planStatus, "READY");
  assert.equal(rest.workout.targetPaceSecPerKm, null);
});

test("a pace from the server's default rule is READY and marked as the rule's", () => {
  const newcomer = { ...tokyoPlan, candidates: [paced(candidate("easy-run", "EASY_RUN", 40, 7, 0.8), "rule_default", [360, 380], 1800, 6000)] };
  const vm = deriveTodayViewModel(input({ plan: newcomer }), atSevenPm);
  assert.equal(vm.planStatus, "READY");
  assert.equal(vm.paceSource, "rule-default");
  assert.equal(vm.workout.targetPaceSecPerKm, 370);
});

test("a ranked run the server gave no pace is FALLBACK with no invented numbers", () => {
  const seekCare = { ...tokyoPlan, candidates: [candidate("seek-care", "REST_AND_SEEK_CARE", 0, 0, 1)] };
  const vm = deriveTodayViewModel(input({ plan: seekCare }), atSevenPm);
  assert.equal(vm.isRestDay, true);
  assert.equal(vm.planStatus, "READY");

  const unpaced = { ...tokyoPlan, candidates: [candidate("easy-run", "EASY_RUN", 40, 7, 1)] };
  const vm2 = deriveTodayViewModel(input({ plan: unpaced }), atSevenPm);
  assert.equal(vm2.planStatus, "FALLBACK");
  assert.equal(vm2.paceSource, "none");
  assert.equal(vm2.workout.targetPaceSecPerKm, null);
  assert.deepEqual(vm2.workout.segments, []);
  assert.equal(vm2.climate.heroPace.single, null);
  assert.equal(vm2.climate.heroPace.range, null);
});

test("server guidance is READY with paceSource server", () => {
  assert.equal(deriveTodayViewModel(input(), atSix).paceSource, "server");
});

test("tied top scores share rank 1 and neither is 首選", () => {
  const vm = deriveTodayViewModel(input({ plan: tokyoPlan }), atSevenPm);
  assert.deepEqual(vm.ranking.map((r) => r.rank), [1, 1, 3, 4]);
  assert.deepEqual(vm.ranking.map((r) => r.isTop), [false, false, false, false]);
  assert.deepEqual(vm.ranking.map((r) => r.fit), [84, 84, 52, 20]);
});

test("a clear winner is ranked 1 and marked top", () => {
  const clear = { ...tokyoPlan, candidates: [{ ...tokyoPlan.candidates[0]!, score: 0.9 }, ...tokyoPlan.candidates.slice(1)] };
  const vm = deriveTodayViewModel(input({ plan: clear }), atSevenPm);
  assert.deepEqual(vm.ranking.map((r) => r.rank), [1, 2, 3, 4]);
  assert.deepEqual(vm.ranking.map((r) => r.isTop), [true, false, false, false]);
});

test("identical server reasons are said once, and each row keeps its own purpose", () => {
  const vm = deriveTodayViewModel(input({ plan: tokyoPlan }), atSevenPm);
  assert.equal(vm.rankingSharedReason, "ACWR 負荷比低於安全區間，可加入適度刺激");
  assert.deepEqual(vm.ranking.map((r) => r.rationale), [null, null, null, null]);
  const purposes = vm.ranking.map((r) => r.purpose);
  assert.equal(new Set(purposes).size, purposes.length);
});

test("different server reasons stay on their rows", () => {
  const mixed = {
    ...tokyoPlan,
    candidates: [{ ...tokyoPlan.candidates[0]!, rationale: ["甲"] }, { ...tokyoPlan.candidates[1]!, rationale: ["乙"] }],
  };
  const vm = deriveTodayViewModel(input({ plan: mixed }), atSevenPm);
  assert.equal(vm.rankingSharedReason, null);
  assert.deepEqual(vm.ranking.map((r) => r.rationale), ["甲", "乙"]);
});

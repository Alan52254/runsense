import assert from "node:assert/strict";
import test from "node:test";
import { summarizeHistoryMetrics } from "./historyMetrics.ts";
import { generateActivityLaps } from "./lapSynthesis.ts";
import type { Activity } from "./types.ts";

function activity(overrides: Partial<Activity>): Activity {
  return {
    id: "activity",
    clientMutationId: "mutation",
    provider: "garmin",
    providerActivityId: "provider-activity",
    performedAtUtc: "2026-08-28T06:00:00Z",
    localTrainingDate: "2026-08-28",
    timezoneSnapshot: "Asia/Taipei",
    durationMinutes: 30,
    rpe: null,
    distanceKm: 5,
    sessionLoad: 100,
    unit: "AU",
    sourceMetric: "GARMIN_DEVICE_LOAD",
    note: "",
    syncState: "SYNCED",
    syncAttempts: 0,
    lastErrorCode: null,
    serverVersion: 1,
    duplicateCandidateOf: null,
    structure: [],
    deviceMetrics: {},
    ...overrides,
  };
}

test("history summary uses only measured device values and duration-weights average HR", () => {
  const summary = summarizeHistoryMetrics([
    activity({
      id: "short",
      durationMinutes: 30,
      distanceKm: 5,
      deviceMetrics: { avgHeartRate: 120, maxHeartRate: 150, avgCadenceStepsPerMin: 170, maxCadenceStepsPerMin: 180, elevationGainM: 20, calories: 300 },
    }),
    activity({
      id: "long",
      durationMinutes: 90,
      distanceKm: 15,
      deviceMetrics: { avgHeartRate: 160, maxHeartRate: 185, avgCadenceStepsPerMin: 178, maxCadenceStepsPerMin: 192, elevationGainM: 60, calories: 900 },
    }),
  ]);

  assert.equal(summary.avgHr, 150);
  assert.equal(summary.peakHr, 185);
  assert.equal(summary.bestAvgCad, 178);
  assert.equal(summary.peakCad, 192);
  assert.equal(summary.totalElev, 80);
  assert.equal(summary.totalCals, 1200);
  assert.equal(summary.totalDist, 20);
});

test("history summary never fabricates physiology for records without device metrics", () => {
  const summary = summarizeHistoryMetrics([
    activity({ provider: "manual", rpe: 9, deviceMetrics: {}, distanceKm: 8 }),
  ]);

  assert.equal(summary.avgHr, null);
  assert.equal(summary.peakHr, null);
  assert.equal(summary.bestAvgCad, null);
  assert.equal(summary.peakCad, null);
  assert.equal(summary.totalElev, null);
  assert.equal(summary.totalCals, null);
  assert.equal(summary.totalDist, 8);
});

test("lap reconstruction does not invent heart rate from RPE", () => {
  const laps = generateActivityLaps([
    activity({ provider: "manual", rpe: 8, distanceKm: 2, durationMinutes: 12 }),
  ][0]);

  assert.equal(laps.length, 2);
  assert.ok(laps.every((lap) => lap.avgHrBpm === null && lap.maxHrBpm === null));
});

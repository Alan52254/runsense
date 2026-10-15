import assert from "node:assert/strict";
import test from "node:test";

import { computeTrainingLoad } from "./trainingLoad.ts";
import { resolveDisplayedTrainingLoad } from "./trainingLoadDisplay.ts";
import type { Activity } from "./types.ts";

function activity(localTrainingDate: string, sessionLoad: number): Activity {
  return {
    id: `activity-${localTrainingDate}`,
    clientMutationId: `mutation-${localTrainingDate}`,
    provider: "garmin",
    providerActivityId: `garmin-${localTrainingDate}`,
    performedAtUtc: `${localTrainingDate}T06:00:00Z`,
    localTrainingDate,
    timezoneSnapshot: "Asia/Tokyo",
    durationMinutes: 60,
    rpe: null,
    distanceKm: 10,
    sessionLoad,
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
  };
}

test("uses the latest recorded date for both load cards and charts when the current window is empty", () => {
  const activities = [
    activity("2026-08-16", 100),
    activity("2026-08-20", 120),
    activity("2026-08-22", 101),
  ];
  const current = computeTrainingLoad(activities, "2026-10-15");

  const display = resolveDisplayedTrainingLoad(activities, current, "2026-10-15");

  assert.equal(display.isHistorical, true);
  assert.deepEqual(display.range, { from: "2026-07-26", to: "2026-08-22" });
  assert.equal(display.trainingLoad.asOfLocalDate, "2026-08-22");
  assert.equal(display.trainingLoad.units[0]?.acuteLoad, 321);
  assert.equal(display.trainingLoad.observationDays, 3);
});

test("keeps the server-provided current result when the current window has activity", () => {
  const activities = [activity("2026-10-12", 80)];
  const current = computeTrainingLoad(activities, "2026-10-15");

  const display = resolveDisplayedTrainingLoad(activities, current, "2026-10-15");

  assert.equal(display.isHistorical, false);
  assert.equal(display.trainingLoad, current);
  assert.deepEqual(display.range, { from: "2026-09-18", to: "2026-10-15" });
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  formatByKind,
  formatDistanceKm,
  formatDistanceMeters,
  formatDurationMin,
  formatDurationSec,
  formatPaceRangeSec,
  formatPaceSec,
} from "./figureFormat.ts";

test("pace seconds per km read as m:ss", () => {
  assert.equal(formatPaceSec(360), "6:00");
  assert.equal(formatPaceSec(319.6), "5:20");
  assert.equal(formatPaceSec(359.7), "6:00");
  assert.equal(formatPaceSec(65), "1:05");
});

test("missing or impossible pace is an em dash", () => {
  assert.equal(formatPaceSec(null), "—");
  assert.equal(formatPaceSec(undefined), "—");
  assert.equal(formatPaceSec(0), "—");
  assert.equal(formatPaceSec(7200), "—");
});

test("pace range shares one dash", () => {
  assert.equal(formatPaceRangeSec(360, 380), "6:00–6:20");
});

test("duration seconds read as m:ss or h:mm:ss", () => {
  assert.equal(formatDurationSec(0), "0:00");
  assert.equal(formatDurationSec(59.6), "1:00");
  assert.equal(formatDurationSec(754), "12:34");
  assert.equal(formatDurationSec(3725), "1:02:05");
  assert.equal(formatDurationSec(null), "—");
});

test("duration minutes read in words per locale", () => {
  assert.equal(formatDurationMin(37.924, "en"), "38 min");
  assert.equal(formatDurationMin(62.638, "en"), "1 hr 3 min");
  assert.equal(formatDurationMin(62.638, "zh-TW"), "1 小時 3 分");
  assert.equal(formatDurationMin(45), "45 分");
});

test("distance switches between m and km", () => {
  assert.equal(formatDistanceMeters(800), "800 m");
  assert.equal(formatDistanceMeters(1000), "1 km");
  assert.equal(formatDistanceMeters(10500), "10.5 km");
  assert.equal(formatDistanceMeters(12345), "12.35 km");
  assert.equal(formatDistanceKm(5), "5 km");
  assert.equal(formatDistanceKm(8.456), "8.46 km");
  assert.equal(formatDistanceMeters(null), "—");
});

test("formatByKind splits value and unit", () => {
  assert.deepEqual(formatByKind({ kind: "pace", secPerKm: 360 }), { value: "6:00", unit: "/km" });
  assert.deepEqual(formatByKind({ kind: "pace", secPerKm: 360, secPerKmHi: 380 }), { value: "6:00–6:20", unit: "/km" });
  assert.deepEqual(formatByKind({ kind: "pace", secPerKm: null }), { value: "—", unit: "" });
  assert.deepEqual(formatByKind({ kind: "duration", seconds: 754 }), { value: "12:34", unit: "" });
  assert.deepEqual(formatByKind({ kind: "distance", meters: 800 }), { value: "800", unit: "m" });
  assert.deepEqual(formatByKind({ kind: "distance", meters: 10500 }), { value: "10.5", unit: "km" });
});

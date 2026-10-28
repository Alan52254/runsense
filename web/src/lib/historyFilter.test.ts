import assert from "node:assert/strict";
import test from "node:test";

import { filterHistoryRows, type HistoryFilter } from "./historyFilter.ts";

const watchInterval = { id: "a", provider: "garmin", providerActivityId: "23929842355", syncState: "SYNCED", duplicateCandidateOf: null, structure: [{ kind: "warmup" }, { kind: "interval" }] };
const manualEasy = { id: "b", provider: "manual", providerActivityId: null, syncState: "SYNCED", duplicateCandidateOf: null, structure: [{ kind: "jog" }] };
const pending = { id: "c", provider: "manual", providerActivityId: null, syncState: "LOCAL_ONLY", duplicateCandidateOf: null, structure: null };
const failed = { id: "d", provider: "garmin", providerActivityId: "1", syncState: "FAILED_TERMINAL", duplicateCandidateOf: null, structure: null };
const dup = { id: "e", provider: "garmin", providerActivityId: "2", syncState: "SYNCED", duplicateCandidateOf: "a", structure: [{ kind: "tempo" }] };
const all = [manualEasy, watchInterval, pending, failed, dup];
const ids = (filter: HistoryFilter) => filterHistoryRows(all, filter).map((r) => r.id);

test("可分析 keeps the order and finds only rows with a watch file", () => {
  assert.deepEqual(ids("analysable"), ["a", "e"]);
});

test("the other filters keep their meaning", () => {
  assert.deepEqual(ids("all"), ["b", "a", "c", "d", "e"]);
  assert.deepEqual(ids("pending"), ["c"]);
  assert.deepEqual(ids("failed"), ["d"]);
  assert.deepEqual(ids("duplicate"), ["e"]);
});

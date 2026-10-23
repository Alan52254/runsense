import assert from "node:assert/strict";
import test from "node:test";

import { historyWorkoutKind, historyWorkoutKindLabel, isAnalysableRow } from "./historyWorkoutKind.ts";

test("a repeat block makes an interval session, whatever surrounds it", () => {
  assert.equal(historyWorkoutKind([{ kind: "warmup" }, { kind: "interval" }, { kind: "cooldown" }]), "interval");
  assert.equal(historyWorkoutKind([{ kind: "warmup" }, { kind: "tempo" }, { kind: "cooldown" }]), "tempo");
  assert.equal(historyWorkoutKind([{ kind: "jog" }]), "easy");
});

test("no structure, no chip: the kind is never guessed", () => {
  assert.equal(historyWorkoutKind([]), null);
  assert.equal(historyWorkoutKind(undefined), null);
  assert.equal(historyWorkoutKind([{ kind: "something-new" }]), null);
});

test("labels are the athlete's words", () => {
  assert.equal(historyWorkoutKindLabel("interval", "zh-TW"), "間歇");
  assert.equal(historyWorkoutKindLabel("tempo", "en"), "Tempo");
});

test("only synced watch recordings of structured sessions offer 查看分析", () => {
  const interval = [{ kind: "warmup" }, { kind: "interval" }];
  const watch = { provider: "garmin", providerActivityId: "23929842355", syncState: "SYNCED" };
  assert.equal(isAnalysableRow({ ...watch, structure: interval }), true);
  assert.equal(isAnalysableRow({ ...watch, structure: [{ kind: "jog" }] }), false);
  assert.equal(isAnalysableRow({ ...watch, provider: "manual", structure: interval }), false);
  assert.equal(isAnalysableRow({ ...watch, syncState: "LOCAL_ONLY", structure: interval }), false);
  // rebuilt from a summary: no watch file behind it
  assert.equal(isAnalysableRow({ ...watch, providerActivityId: "synthetic-tokyo-gapfill-20261016", structure: interval }), false);
  assert.equal(isAnalysableRow({ ...watch, providerActivityId: null, structure: interval }), false);
});

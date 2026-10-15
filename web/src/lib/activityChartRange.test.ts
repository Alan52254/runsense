import assert from "node:assert/strict";
import test from "node:test";

import { resolveActivityChartRange } from "./activityChartRange.ts";

test("uses the latest recorded activity when the current 28-day window is empty", () => {
  const range = resolveActivityChartRange(
    [
      { localTrainingDate: "2026-04-24" },
      { localTrainingDate: "2026-08-22" },
      { localTrainingDate: "2026-08-10" },
    ],
    "2026-10-15",
  );

  assert.deepEqual(range, { from: "2026-07-26", to: "2026-08-22" });
});

test("keeps the current 28-day window when it contains a recorded activity", () => {
  const range = resolveActivityChartRange(
    [{ localTrainingDate: "2026-10-01" }, { localTrainingDate: "2026-08-22" }],
    "2026-10-15",
  );

  assert.deepEqual(range, { from: "2026-09-18", to: "2026-10-15" });
});

test("keeps the current window when there are no activities", () => {
  assert.deepEqual(resolveActivityChartRange([], "2026-10-15"), {
    from: "2026-09-18",
    to: "2026-10-15",
  });
});

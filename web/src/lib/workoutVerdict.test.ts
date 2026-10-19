import assert from "node:assert/strict";
import test from "node:test";

import { repGap, workoutVerdict } from "./workoutVerdict.ts";
import type { VerdictInput } from "./workoutVerdict.ts";

function rep(n: number, extra: Record<string, unknown> = {}) {
  return { index: n * 2, role: "work" as const, rep_number: n, pace_s_per_km: 250, ...extra };
}

function finding(code: string, severity: "critical" | "warning" | "positive" | "info", title: string, advice: string | null = null) {
  return { code, severity, title, detail: `${title} detail`, advice, evidence: {} };
}

/* Tokyo 8/11 08:25: 2000m-1000m-800m, every rep inside ±1.5% */
const tokyo: VerdictInput = {
  segment_stats: [
    rep(1, { target_pace_s_per_km: 265, target_dev_pct: 0.2 }),
    { index: 3, role: "rest" },
    rep(2, { target_pace_s_per_km: 215, target_dev_pct: 0.9 }),
    { index: 5, role: "rest" },
    rep(3, { target_pace_s_per_km: 250, target_dev_pct: 0.5 }),
  ],
  findings: [
    finding("within_rep_fade", "warning", "每趟前半段太快", "起跑後前 100m 刻意放鬆"),
    finding("consistency", "positive", "每趟都穩穩貼著自己的目標"),
    finding("target", "positive", "貼近課表要求"),
    finding("near_max", "info", "強度接近最大心率"),
    finding("recovery", "info", "休息時的心率下降"),
    finding("linked_warmup", "info", "暖身另有紀錄"),
    finding("linked_cooldown", "info", "收操另有紀錄"),
  ],
};

test("all reps within tolerance and one thing to fix reads as one line", () => {
  const v = workoutVerdict(tokyo);
  assert.equal(v.headline, "3 趟都在要求 ±1.5% 內 · 待改進：每趟前半段太快");
  assert.equal(v.within, 3);
  assert.equal(v.graded, 3);
});

test("the next-time line is the advice attached to the top improvement", () => {
  assert.equal(workoutVerdict(tokyo).next, "起跑後前 100m 刻意放鬆");
  const clean = { ...tokyo, findings: tokyo.findings.filter((f) => f.severity !== "warning") };
  assert.equal(workoutVerdict(clean).next, null);
  assert.equal(workoutVerdict(clean).headline, "3 趟都在要求 ±1.5% 內");
});

test("counts only the reps inside the tolerance, faster or slower", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { target_dev_pct: -2.4 }),
      rep(2, { target_dev_pct: 1.5 }),
      rep(3, { target_dev_pct: 3.1 }),
      rep(4, { target_dev_pct: -0.4 }),
    ],
  });
  assert.equal(v.headline, "4 趟中 2 趟在要求 ±1.5% 內");
  assert.equal(v.within, 2);
});

test("a ceiling target counts every faster rep as met", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { target_dev_pct: -4.0, target_mode: "max" }),
      rep(2, { target_dev_pct: 2.0, target_mode: "max" }),
    ],
  });
  assert.equal(v.headline, "2 趟中 1 趟在要求內");
});

test("without a prescription the verdict states the reps' own pace, not a grade", () => {
  const v = workoutVerdict({
    findings: [finding("fade", "warning", "後段掉速", "下次前段每趟收 1–2 秒")],
    segment_stats: [rep(1), rep(2), rep(3)],
    summary: { mean_work_pace_s_per_km: 250.4 },
  });
  assert.equal(v.headline, "3 趟平均 4:10 /km · 待改進：後段掉速");
  assert.equal(v.graded, 0);
});

test("a continuous run reads its average pace", () => {
  const v = workoutVerdict({ findings: [], segment_stats: [], summary: { split_mean_pace_s_per_km: 341 } });
  assert.equal(v.headline, "平均配速 5:41 /km");
});

test("findings that restate the verdict or the table are not repeated", () => {
  const v = workoutVerdict(tokyo);
  assert.deepEqual(v.notes.map((f) => f.code), []);
  assert.deepEqual(v.recovery.map((f) => f.code), ["near_max", "recovery", "linked_warmup", "linked_cooldown"]);
});

test("pace findings beyond the top improvement stay beside the verdict", () => {
  const v = workoutVerdict({
    ...tokyo,
    findings: [
      finding("first_rep_fast", "warning", "第一趟衝太快", "第一趟收一點"),
      finding("fade", "warning", "後段掉速"),
      finding("interruption", "info", "第 2 趟中途停下"),
      finding("short_cooldown", "info", "收操偏短"),
      finding("history", "positive", "比上次快"),
    ],
  });
  assert.equal(v.headline, "3 趟都在要求 ±1.5% 內 · 待改進：第一趟衝太快");
  assert.deepEqual(v.notes.map((f) => f.code), ["fade", "history"]);
  assert.deepEqual(v.recovery.map((f) => f.code), ["short_cooldown"]);
});

test("a rep's gap is worded as slower or faster and flagged only outside tolerance", () => {
  assert.deepEqual(repGap(rep(1, { nominal_m: 2000, target_dev_pct: 0.2 })), { text: "慢 0.2%", within: true, direction: "slow" });
  assert.deepEqual(repGap(rep(1, { nominal_m: 1000, target_dev_pct: -2.4 })), { text: "快 2.4%", within: false, direction: "fast" });
  assert.deepEqual(repGap(rep(1, { nominal_m: 1000, target_dev_pct: 0 })), { text: "持平", within: true, direction: null });
});

test("short reps state their gap in seconds", () => {
  assert.deepEqual(repGap(rep(1, { nominal_m: 400, target_dev_pct: 2.0, target_dev_s: 1.6 })), { text: "慢 1.6 秒", within: false, direction: "slow" });
});

test("a ceiling target is met by any faster rep", () => {
  assert.equal(repGap(rep(1, { nominal_m: 1000, target_dev_pct: -3.0, target_mode: "max" })).within, true);
});

test("a rep without a target has no gap", () => {
  assert.deepEqual(repGap(rep(1)), { text: "—", within: null, direction: null });
});

test("the coach's own 下次 line leads and is not repeated in the write-up", () => {
  const v = workoutVerdict({
    ...tokyo,
    narrative: "今天最關鍵的是每趟後半段都比前半段慢 3.9%。\n\n下次：起跑後前 100m 刻意放鬆，後半段再加壓。",
  });
  assert.equal(v.next, "起跑後前 100m 刻意放鬆，後半段再加壓。");
  assert.equal(v.narrative, "今天最關鍵的是每趟後半段都比前半段慢 3.9%。");
});

test("a write-up without a 下次 line is kept whole", () => {
  const v = workoutVerdict({ ...tokyo, narrative: "穩定的一課。" });
  assert.equal(v.next, "起跑後前 100m 刻意放鬆");
  assert.equal(v.narrative, "穩定的一課。");
});

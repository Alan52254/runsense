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

/* Tokyo 8/14: 2000m-1000m-800m, every rep inside ±1.5% of the prescription.
 * Halves (前半 / 後半, s/km) are the real saved numbers: rep 1 is a negative
 * split, reps 2 and 3 fade. */
const tokyo: VerdictInput = {
  segment_stats: [
    rep(1, { nominal_m: 2000, target_pace_s_per_km: 265, target_dev_pct: 0.2, first_half_pace: 267, second_half_pace: 262 }),
    { index: 3, role: "rest" },
    rep(2, { nominal_m: 1000, target_pace_s_per_km: 215, target_dev_pct: 0.9, first_half_pace: 211, second_half_pace: 221 }),
    { index: 5, role: "rest" },
    rep(3, { nominal_m: 800, target_pace_s_per_km: 250, target_dev_pct: 0.5, first_half_pace: 236, second_half_pace: 258 }),
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

/* Tokyo 8/07: 2 sets of 8 x 200m against 36 s; 200m reps have no half splits */
const DEV_8_07 = [8.3, -2.8, 2.8, -2.8, -2.8, 2.8, 5.6, 5.6, 2.8, -8.3, 0, 5.6, 0, -2.8, -2.8, 8.3];
const tokyo0807: VerdictInput = {
  segment_stats: DEV_8_07.flatMap((dev, i) => [
    rep(i + 1, { nominal_m: 200, target_pace_s_per_km: 180, target_dev_pct: dev, target_dev_s: Math.round(dev * 0.36) }),
    { index: i * 2 + 1, role: "rest" as const },
  ]),
  findings: [finding("consistency", "warning", "每趟離目標的差距忽大忽小")],
};

test("the headline counts the reps in tolerance and the halves, never a verdict the table cannot show", () => {
  const v = workoutVerdict(tokyo);
  assert.equal(v.headline, "3 趟都在要求 ±1.5% 內 · 3 趟中 2 趟後半段比前半段慢");
  assert.equal(v.within, 3);
  assert.equal(v.graded, 3);
  assert.ok(!v.headline.includes("太快"));
});

test("the next line names the rep whose halves differ most, with the table's own numbers", () => {
  assert.equal(workoutVerdict(tokyo).next, "留意第 3 趟：後半段比前半段慢 9.3%（3:56 → 4:18）");
});

test("the server's 每趟前半段太快 finding is not shown beside a table that contradicts it", () => {
  const v = workoutVerdict(tokyo);
  assert.ok(![...v.notes, ...v.recovery].some((f) => f.code === "within_rep_fade"));
  assert.deepEqual(v.notes.map((f) => f.code), []);
});

test("reps all ahead at the second half read as negative splits and give no next line", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { target_dev_pct: 0.3, first_half_pace: 250, second_half_pace: 245 }),
      rep(2, { target_dev_pct: -0.2, first_half_pace: 250, second_half_pace: 249 }),
    ],
  });
  assert.equal(v.headline, "2 趟都在要求 ±1.5% 內 · 2 趟後半段都沒有比前半段慢");
  assert.equal(v.next, null);
});

test("every rep slower in the second half says so", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { target_dev_pct: 0.3, first_half_pace: 240, second_half_pace: 245 }),
      rep(2, { target_dev_pct: 0.2, first_half_pace: 240, second_half_pace: 250 }),
    ],
  });
  assert.equal(v.headline, "2 趟都在要求 ±1.5% 內 · 2 趟後半段都比前半段慢");
  assert.equal(v.next, "留意第 2 趟：後半段比前半段慢 4.2%（4:00 → 4:10）");
});

test("reps missing a half are left out of the half count and the headline says how many were read", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { target_dev_pct: 0.3, first_half_pace: 240, second_half_pace: 250 }),
      rep(2, { target_dev_pct: 0.2 }),
      rep(3, { target_dev_pct: 0.1, first_half_pace: 240, second_half_pace: 238 }),
    ],
  });
  assert.equal(v.headline, "3 趟都在要求 ±1.5% 內 · 有前後半資料的 2 趟中 1 趟後半段比前半段慢");
});

test("a rep with only one half is not a split", () => {
  const v = workoutVerdict({ findings: [], segment_stats: [rep(1, { target_dev_pct: 0.3, first_half_pace: 240 })] });
  assert.equal(v.headline, "1 趟都在要求 ±1.5% 內");
});

test("a rep outside the tolerance leads the next line, by its gap in the table's unit", () => {
  const v = workoutVerdict(tokyo0807);
  assert.equal(v.headline, "16 趟中 2 趟在要求 ±1.5% 內");
  assert.equal(v.next, "留意偏離要求最大的 3 趟：第 1 趟慢 3.0 秒、第 10 趟快 3.0 秒、第 16 趟慢 3.0 秒");
});

test("a single worst rep is named alone", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { nominal_m: 1000, target_dev_pct: 0.4 }),
      rep(2, { nominal_m: 1000, target_dev_pct: 3.1 }),
      rep(3, { nominal_m: 1000, target_dev_pct: -2.0 }),
    ],
  });
  assert.equal(v.headline, "3 趟中 1 趟在要求 ±1.5% 內");
  assert.equal(v.next, "留意偏離要求最大的第 2 趟：慢 3.1%");
});

test("a ceiling target never counts a faster rep as the worst", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { nominal_m: 1000, target_dev_pct: -6.0, target_mode: "max" }),
      rep(2, { nominal_m: 1000, target_dev_pct: 2.0, target_mode: "max" }),
    ],
  });
  assert.equal(v.next, "留意偏離要求最大的第 2 趟：慢 2.0%");
});

test("without a prescription the halves are still read from the reps", () => {
  const v = workoutVerdict({
    findings: [],
    segment_stats: [
      rep(1, { first_half_pace: 240, second_half_pace: 246 }),
      rep(2, { first_half_pace: 240, second_half_pace: 236 }),
    ],
    summary: { mean_work_pace_s_per_km: 241 },
  });
  assert.equal(v.headline, "2 趟平均 4:01 /km · 2 趟中 1 趟後半段比前半段慢");
  assert.equal(v.graded, 0);
  assert.equal(v.next, "留意第 1 趟：後半段比前半段慢 2.5%（4:00 → 4:06）");
});

test("a run with no prescription and no halves states only what was run", () => {
  const v = workoutVerdict({
    findings: [finding("fade", "warning", "後段掉速", "下次前段每趟收 1–2 秒")],
    segment_stats: [rep(1), rep(2), rep(3)],
    summary: { mean_work_pace_s_per_km: 250.4 },
  });
  assert.equal(v.headline, "3 趟平均 4:10 /km");
  assert.equal(v.next, null);
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

test("a continuous run reads its average pace", () => {
  const v = workoutVerdict({ findings: [], segment_stats: [], summary: { split_mean_pace_s_per_km: 341 } });
  assert.equal(v.headline, "平均配速 5:41 /km");
  assert.equal(v.next, null);
});

test("recovery findings and the pace findings the headline does not state stay in their lists", () => {
  assert.deepEqual(workoutVerdict(tokyo).recovery.map((f) => f.code), ["near_max", "recovery", "linked_warmup", "linked_cooldown"]);
  const more = workoutVerdict({
    ...tokyo,
    findings: [
      finding("first_rep_fast", "warning", "第一趟衝太快", "第一趟收一點"),
      finding("interruption", "info", "第 2 趟中途停下"),
      finding("short_cooldown", "info", "收操偏短"),
      finding("history", "positive", "比上次快"),
    ],
  });
  assert.deepEqual(more.notes.map((f) => f.code), ["first_rep_fast", "history"]);
  assert.deepEqual(more.recovery.map((f) => f.code), ["short_cooldown"]);
});

test("the stored write-up is kept whole, including its own 下次 line", () => {
  const text = "今天最關鍵的是每趟後半段都比前半段慢 3.9%。\n\n下次：起跑後前 100m 刻意放鬆。";
  assert.equal(workoutVerdict({ ...tokyo, narrative: text }).narrative, text);
});

test("a rep's gap is worded as slower or faster and flagged only outside tolerance", () => {
  assert.deepEqual(repGap(rep(1, { nominal_m: 2000, target_dev_pct: 0.2 })), { text: "慢 0.2%", within: true, direction: "slow", unit: "percent" });
  assert.deepEqual(repGap(rep(1, { nominal_m: 1000, target_dev_pct: -2.4 })), { text: "快 2.4%", within: false, direction: "fast", unit: "percent" });
  assert.deepEqual(repGap(rep(1, { nominal_m: 1000, target_dev_pct: 0 })), { text: "持平", within: true, direction: null, unit: "percent" });
});

test("short reps state their gap in seconds", () => {
  assert.deepEqual(repGap(rep(1, { nominal_m: 400, target_dev_pct: 2.0, target_dev_s: 1.6 })), { text: "慢 1.6 秒", within: false, direction: "slow", unit: "seconds" });
});

test("a ceiling target is met by any faster rep", () => {
  assert.equal(repGap(rep(1, { nominal_m: 1000, target_dev_pct: -3.0, target_mode: "max" })).within, true);
});

test("a rep without a target has no gap", () => {
  assert.deepEqual(repGap(rep(1)), { text: "—", within: null, direction: null, unit: null });
});

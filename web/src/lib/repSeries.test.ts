import assert from "node:assert/strict";
import test from "node:test";

import { REP_CHART, repSeries } from "./repSeries.ts";
import type { RepSeriesInput } from "./repSeries.ts";
import { formatByKind } from "./figureFormat.ts";

function work(index: number, rep: number, extra: Record<string, unknown> = {}) {
  return {
    index, role: "work" as const, rep_number: rep, nominal_m: 1000, nominal_s: null, distance_m: 1004,
    moving_s: 220, elapsed_s: 220, interruptions_s: 0, pace_s_per_km: 220, avg_hr: 170, hr_end: 180, ...extra,
  };
}

function rest(index: number, extra: Record<string, unknown> = {}) {
  return { index, role: "rest" as const, elapsed_s: 90, moving_s: 80, interruptions_s: 0, rest_type: "walking" as const, hr_drop: 25, ...extra };
}

/* Tokyo 8/14 08:25 as the backend saved it: 2000m-1000m-800m */
const tokyo: RepSeriesInput = {
  segment_stats: [
    work(0, 1, { nominal_m: 2000, moving_s: 531, pace_s_per_km: 265.5, target_pace_s_per_km: 265, target_label: "4:25/km", target_dev_pct: 0.2, target_dev_s: 1, avg_hr: 142, hr_end: 144, first_half_pace: 267.2, second_half_pace: 262.2 }),
    rest(1, { elapsed_s: 299, rest_type: "standing", hr_drop: 32 }),
    work(2, 2, { nominal_m: 1000, moving_s: 217, pace_s_per_km: 217, target_pace_s_per_km: 215, target_label: "3:35/km", target_dev_pct: 0.9, target_dev_s: 2, avg_hr: 186, hr_end: 188 }),
    rest(3, { elapsed_s: 313, rest_type: "walking", hr_drop: 14 }),
    work(4, 3, { nominal_m: 800, moving_s: 201, pace_s_per_km: 251.2, target_pace_s_per_km: 250, target_label: "4:10/km", target_dev_pct: 0.5, target_dev_s: 1, avg_hr: 162, hr_end: 182 }),
    { index: 5, role: "cooldown" as const, elapsed_s: 11, moving_s: 4, interruptions_s: 0 },
  ],
  summary: { mean_work_pace_s_per_km: 249.7 },
};

test("one row per rep, in order, with the table's figures", () => {
  const s = repSeries(tokyo, 640);
  assert.deepEqual(s.reps.map((r) => r.repNumber), [1, 2, 3]);
  const [first, second] = s.reps;
  assert.equal(first.paceSec, 265.5);
  assert.equal(first.paceText, "4:26");
  assert.equal(first.targetSec, 265);
  assert.equal(first.targetText, "4:25/km");
  assert.equal(first.deltaSec, 1);
  assert.equal(first.gap.text, "慢 0.2%");
  assert.equal(first.distanceText, "2000 m");
  assert.equal(first.timeText, "8:51");
  assert.equal(first.halvesText, "4:27 / 4:22");
  assert.equal(first.avgHr, 142);
  assert.equal(first.endHr, 144);
  assert.equal(first.hrText, "142 / 144");
  assert.equal(first.restSec, 299);
  assert.equal(first.restText, "4:59");
  assert.equal(first.restKind, "站著／暫停");
  assert.equal(first.hrDrop, 32);
  assert.equal(first.hrDropText, "−32 bpm");
  assert.equal(second.restKind, "走路");
  // the last rep runs into the cool-down, not a rest
  assert.equal(s.reps[2].restSec, null);
  assert.equal(s.reps[2].restText, "—");
  assert.equal(s.reps[2].hrDropText, "—");
});

test("every heart-rate point sits on its bar's centre", () => {
  for (const width of [240, 358, 640, 1100]) {
    const s = repSeries(tokyo, width);
    for (const r of s.reps) {
      assert.ok(r.bar && r.hr);
      assert.equal(r.hr.x, r.bar.x + r.bar.w / 2);
      assert.equal(r.hr.x, r.bar.cx);
    }
  }
});

test("chart labels are the table's cells", () => {
  const s = repSeries(tokyo, 640);
  for (const r of s.reps) {
    // the table's Figure formats pace with the same formatter as the bar label
    assert.equal(formatByKind({ kind: "pace", secPerKm: r.paceSec }).value, r.bar?.label);
    assert.equal(r.paceText, r.bar?.label);
    // the HR point is the table's end-of-rep heart rate
    assert.equal(r.hr?.label, String(r.endHr));
    assert.ok(r.hrText.endsWith(`/ ${r.hr?.label}`));
  }
  assert.equal(s.mean.label, "4:10");
});

test("heart-rate labels never reach into the pace labels' band", () => {
  const s = repSeries(tokyo, 640);
  const lowestHr = Math.max(...s.reps.map((r) => (r.hr ? r.hr.y + REP_CHART.hrDot : -Infinity)));
  const highestPaceLabel = Math.min(...s.reps.map((r) => (r.bar ? r.bar.labelY - REP_CHART.paceLabelSize : Infinity)));
  assert.ok(lowestHr < highestPaceLabel, `${lowestHr} < ${highestPaceLabel}`);
  for (const r of s.reps) {
    assert.ok(r.hr && r.hr.labelY - REP_CHART.hrLabelSize >= 0, "HR label inside the frame");
  }
});

test("taller means faster, and a rep slow beyond the tolerance is dimmed", () => {
  const s = repSeries({
    segment_stats: [
      work(0, 1, { pace_s_per_km: 180, target_pace_s_per_km: 180, target_dev_pct: 0, target_dev_s: 0, nominal_m: 200 }),
      work(1, 2, { pace_s_per_km: 195, target_pace_s_per_km: 180, target_dev_pct: 8.3, target_dev_s: 3, nominal_m: 200 }),
      work(2, 3, { pace_s_per_km: 175, target_pace_s_per_km: 180, target_dev_pct: -2.8, target_dev_s: -1, nominal_m: 200 }),
    ],
  }, 640);
  const [even, slow, fast] = s.reps;
  assert.ok(fast.bar!.h > even.bar!.h && even.bar!.h > slow.bar!.h);
  assert.deepEqual(s.reps.map((r) => r.dimmed), [false, true, false]);
  assert.equal(slow.gap.text, "慢 3.0 秒");
  assert.equal(fast.gap.text, "快 1.0 秒");
});

test("a rep without heart rate gets no point and the line runs past it", () => {
  const s = repSeries({
    segment_stats: [
      work(0, 1, { hr_end: 150 }),
      work(1, 2, { hr_end: null, avg_hr: null }),
      work(2, 3, { hr_end: 170 }),
    ],
  }, 640);
  assert.equal(s.reps[1].hr, null);
  assert.equal(s.reps[1].hrText, "— / —");
  assert.ok(s.reps[1].bar, "the bar is still drawn");
  const points = s.hrLine.split(" ");
  assert.equal(points.length, 2);
  assert.equal(points[0], `${s.reps[0].hr!.x},${s.reps[0].hr!.y}`);
  assert.equal(points[1], `${s.reps[2].hr!.x},${s.reps[2].hr!.y}`);
});

test("no heart rate at all: no points and no line", () => {
  const s = repSeries({ segment_stats: [work(0, 1, { hr_end: null }), work(1, 2, { hr_end: null })] }, 640);
  assert.ok(s.reps.every((r) => r.hr === null));
  assert.equal(s.hrLine, "");
  assert.equal(s.hasHr, false);
});

test("the mean falls back to the reps when the summary has none, and narrow frames widen to fit", () => {
  const s = repSeries({ segment_stats: [work(0, 1, { pace_s_per_km: 200 }), work(1, 2, { pace_s_per_km: 210 })] }, 100);
  assert.equal(s.mean.sec, 205);
  assert.ok(s.width >= REP_CHART.left + REP_CHART.right + 2 * REP_CHART.minSlot);
  // the mean line sits between the two bar tops
  const tops = s.reps.map((r) => r.bar!.y);
  assert.ok(s.mean.y > Math.min(...tops) && s.mean.y < Math.max(...tops));
});

test("summary figures", () => {
  const s = repSeries(tokyo, 640);
  assert.equal(s.restMeanSec, 306);
});

test("each pace label sits on its own bar and never on the target tick", () => {
  const cases: RepSeriesInput[] = [tokyo];
  // the target drawn every distance above, at, and below the bar top
  for (const dev of [-12, -6, -3, -1, 0, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20]) {
    cases.push({
      segment_stats: [
        work(0, 1, { pace_s_per_km: 165 }),
        work(1, 2, { pace_s_per_km: 180 + dev, target_pace_s_per_km: 180, target_dev_pct: dev / 1.8, target_dev_s: dev / 5, nominal_m: 200 }),
        work(2, 3, { pace_s_per_km: 195 }),
      ],
    });
  }
  for (const input of cases) {
    for (const width of [240, 358, 880]) {
      for (const r of repSeries(input, width).reps) {
        const b = r.bar!;
        assert.ok(b.y - b.labelY >= 0 && b.y - b.labelY <= REP_CHART.paceLabelMaxGap, `rep ${r.repNumber}: label ${b.y - b.labelY}px above its bar`);
        if (b.targetY === null) continue;
        assert.ok(b.tick.length > 0, "the tick is drawn");
        for (const seg of b.tick) {
          const crossX = seg.x1 < b.labelBox.x2 && b.labelBox.x1 < seg.x2;
          const crossY = b.targetY - REP_CHART.tickHalf < b.labelBox.y2 && b.labelBox.y1 < b.targetY + REP_CHART.tickHalf;
          assert.ok(!(crossX && crossY), `rep ${r.repNumber}: label and tick overlap`);
        }
      }
    }
  }
});

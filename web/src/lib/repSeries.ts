/* The per-rep (逐趟) series behind the 每趟配速 chart and the rep table.
 * Pure: it reads the analysis result the backend returned and lays it out.
 * The chart and the table both read these rows, so a pace or heart rate
 * can only ever be written one way. Each heart-rate point is placed at its
 * bar's centre by the same expression, and heart rate has a band of its own
 * above the bars so its labels never land on the pace labels. */

import type { SegmentStatsWire } from "../data/apiClient.ts";
import { formatDurationSec, formatPaceSec } from "./figureFormat.ts";
import { repGap } from "./workoutVerdict.ts";
import type { RepGap } from "./workoutVerdict.ts";

type Stat = Partial<SegmentStatsWire> & Pick<SegmentStatsWire, "index" | "role"> & {
  target_mode?: "exact" | "max";
};

export interface RepSeriesInput {
  segment_stats: Stat[];
  summary?: Record<string, unknown>;
}

/** Chart geometry in SVG px. The label sizes are the font sizes the
 *  stylesheet gives .rep-chart-value and .rep-chart-hr-label. */
export const REP_CHART = {
  left: 68,
  right: 12,
  minSlot: 48,
  maxBar: 48,
  paceLabelSize: 16,
  /** the pace label's digits: cap height, and a generous width per glyph */
  paceLabelCap: 12,
  paceGlyphW: 7.5,
  /** baseline sits this far above the bar top */
  paceLabelGap: 3,
  /** at most this far from the bar top to the label's baseline */
  paceLabelMaxGap: 8,
  /** target tick: half its stroke, and how far it reaches past the bar */
  tickHalf: 1.5,
  tickReach: 8,
  hrLabelSize: 13,
  hrDot: 4,
  /** first possible HR point: room for its label above it */
  hrPointTop: 24,
  hrBand: 56,
  bandGap: 12,
  plotH: 150,
  bottom: 30,
} as const;

const REST_TYPE_LABEL = { standing: "站著／暫停", walking: "走路", jogging: "慢跑" } as const;
const DASH = "—";

export interface RepBar {
  /** left edge, width, centre */
  x: number;
  w: number;
  cx: number;
  /** top edge and height; taller is faster */
  y: number;
  h: number;
  /** the pace written just above the bar: baseline, and its box */
  label: string;
  labelY: number;
  labelBox: { x1: number; x2: number; y1: number; y2: number };
  /** the rep's required pace, as a tick across the bar: one segment, or
   *  two when it runs behind the label and breaks around it */
  targetY: number | null;
  tick: { x1: number; x2: number }[];
}

export interface RepHrPoint {
  x: number;
  y: number;
  label: string;
  labelY: number;
}

export interface RepRow {
  index: number;
  repNumber: number;
  distanceText: string;
  timeSec: number | null;
  timeText: string;
  interruptionsSec: number;
  paceSec: number | null;
  paceText: string;
  targetSec: number | null;
  targetText: string;
  /** seconds over (+) or under (−) the target across the rep */
  deltaSec: number | null;
  gap: RepGap;
  /** slow beyond the tolerance: drawn in the dimmed orange */
  dimmed: boolean;
  avgHr: number | null;
  endHr: number | null;
  /** "平均 / 結束" */
  hrText: string;
  halvesText: string;
  restSec: number | null;
  restText: string;
  restKind: string;
  hrDrop: number | null;
  hrDropText: string;
  /** chart x position of the rep number */
  axisX: number;
  bar: RepBar | null;
  hr: RepHrPoint | null;
}

export interface RepSeries {
  reps: RepRow[];
  width: number;
  height: number;
  /** pace plot: top of the fastest bar and the baseline */
  paceTop: number;
  base: number;
  hasHr: boolean;
  /** HR band, for its caption */
  hrBandTop: number;
  hrBandBottom: number;
  /** "x,y x,y …" through the reps that have heart rate */
  hrLine: string;
  mean: { sec: number | null; label: string; y: number | null };
  restMeanSec: number | null;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const positive = (v: unknown): number | null => {
  const n = num(v);
  return n !== null && n > 0 ? n : null;
};

function distanceText(r: Stat): string {
  if (r.nominal_m) return `${r.nominal_m} m`;
  if (r.nominal_s) return `${r.nominal_s} 秒`;
  return typeof r.distance_m === "number" ? `${Math.round(r.distance_m)} m` : DASH;
}

function restAfter(rep: Stat, byIndex: Map<number, Stat>): Stat | null {
  const next = byIndex.get(rep.index + 1);
  return next && (next.role === "rest" || next.role === "set_rest") ? next : null;
}

const overlaps = (a1: number, a2: number, b1: number, b2: number) => a1 < b2 && b1 < a2;

/** The pace label belongs to its bar: its baseline sits just above the bar
 *  top, never more than paceLabelMaxGap away. When the target tick would run
 *  through it, the label sits just above the tick if the bar top is right
 *  under it; otherwise the tick breaks around the label. */
function placePaceLabel(cx: number, w: number, barTop: number, targetY: number | null, label: string) {
  const C = REP_CHART;
  const half = (label.length * C.paceGlyphW) / 2;
  const box = (base: number) => ({ x1: cx - half, x2: cx + half, y1: base - C.paceLabelCap, y2: base });
  let labelY = barTop - C.paceLabelGap;
  let tick: { x1: number; x2: number }[] = [];
  if (targetY !== null) {
    const t1 = targetY - C.tickHalf - 1;
    const t2 = targetY + C.tickHalf + 1;
    const x1 = cx - w / 2 - C.tickReach;
    const x2 = cx + w / 2 + C.tickReach;
    tick = [{ x1, x2 }];
    if (overlaps(labelY - C.paceLabelCap, labelY, t1, t2)) {
      if (barTop - (t1 - 1) <= C.paceLabelMaxGap) labelY = t1 - 1;
      else {
        // broken around the label, each side still reading as a tick
        const gapL = cx - half - 2;
        const gapR = cx + half + 2;
        tick = [{ x1: Math.min(x1, gapL - 6), x2: gapL }, { x1: gapR, x2: Math.max(x2, gapR + 6) }];
      }
    }
  }
  return { label, labelY, labelBox: box(labelY), targetY, tick };
}

export function repSeries(result: RepSeriesInput, frameWidth: number): RepSeries {
  const C = REP_CHART;
  const stats = result.segment_stats;
  const byIndex = new Map(stats.map((s) => [s.index, s]));
  const work = stats.filter((s) => s.role === "work");

  const width = Math.max(frameWidth, C.left + C.right + work.length * C.minSlot);
  const slot = (width - C.left - C.right) / Math.max(1, work.length);
  const barW = Math.min(C.maxBar, slot * 0.56);

  const paces = work.map((r) => positive(r.pace_s_per_km)).filter((p): p is number => p !== null && formatPaceSec(p) !== DASH);
  const targets = work.map((r) => positive(r.target_pace_s_per_km)).filter((t): t is number => t !== null);
  const hrs = work.map((r) => num(r.hr_end)).filter((h): h is number => h !== null);
  const hasHr = hrs.length > 0;

  // HR band on top, then the pace plot; the gap keeps the two label rows apart
  const hrBandTop = C.hrPointTop - C.hrLabelSize - 9;
  const hrBandBottom = hasHr ? C.hrPointTop + C.hrBand + C.hrDot : 0;
  const paceTop = hrBandBottom + C.bandGap + C.paceLabelSize + 8;
  const base = paceTop + C.plotH;
  const height = base + C.bottom;

  const all = [...paces, ...targets];
  const lo = all.length ? Math.min(...all) : 0;
  const slowest = all.length ? Math.max(...all) : 1;
  const range = Math.max(10, slowest - lo);
  const hi = slowest + range * 0.5;
  // faster pace -> smaller y -> taller bar
  const yPace = (p: number) => paceTop + ((p - lo) / (hi - lo)) * C.plotH;

  const hrLo = hasHr ? Math.min(...hrs) - 2 : 0;
  const hrHi = hasHr ? Math.max(...hrs) + 2 : 1;
  const yHr = (h: number) => C.hrPointTop + ((hrHi - h) / (hrHi - hrLo)) * C.hrBand;

  const summaryMean = positive(result.summary?.mean_work_pace_s_per_km);
  const meanSec = summaryMean ?? (paces.length ? paces.reduce((a, b) => a + b, 0) / paces.length : null);

  const reps: RepRow[] = work.map((r, i) => {
    const cx = C.left + slot * i + slot / 2;
    const paceSec = positive(r.pace_s_per_km);
    const paceText = formatPaceSec(paceSec);
    const targetSec = positive(r.target_pace_s_per_km);
    const gap = repGap(r);
    const avgHr = num(r.avg_hr);
    const endHr = num(r.hr_end);
    const rest = restAfter(r, byIndex);
    const restSec = rest ? num(rest.elapsed_s) : null;
    const hrDrop = rest ? num(rest.hr_drop) : null;
    const timeSec = num(r.moving_s);

    let bar: RepBar | null = null;
    if (paceSec !== null && paceText !== DASH) {
      const y = yPace(paceSec);
      const targetY = targetSec !== null ? yPace(targetSec) : null;
      bar = { x: cx - barW / 2, w: barW, cx, y, h: Math.max(2, base - y), ...placePaceLabel(cx, barW, y, targetY, paceText) };
    }

    const hr: RepHrPoint | null = endHr === null ? null : {
      x: cx,
      y: yHr(endHr),
      label: String(endHr),
      labelY: yHr(endHr) - 9,
    };

    return {
      index: r.index,
      repNumber: r.rep_number ?? i + 1,
      distanceText: distanceText(r),
      timeSec,
      timeText: formatDurationSec(timeSec),
      interruptionsSec: num(r.interruptions_s) ?? 0,
      paceSec,
      paceText,
      targetSec,
      targetText: r.target_label ?? DASH,
      deltaSec: num(r.target_dev_s),
      gap,
      dimmed: bar !== null && gap.direction === "slow" && gap.within === false,
      avgHr,
      endHr,
      hrText: `${avgHr ?? DASH} / ${endHr ?? DASH}`,
      halvesText: r.first_half_pace && r.second_half_pace
        ? `${formatPaceSec(r.first_half_pace)} / ${formatPaceSec(r.second_half_pace)}`
        : DASH,
      restSec,
      restText: formatDurationSec(restSec),
      restKind: rest
        ? [rest.role === "set_rest" ? "組間" : "", rest.rest_type ? REST_TYPE_LABEL[rest.rest_type] : ""].filter(Boolean).join(" · ")
        : "",
      hrDrop,
      hrDropText: hrDrop === null ? DASH : hrDrop >= 0 ? `−${hrDrop} bpm` : `升 ${-hrDrop} bpm`,
      axisX: cx,
      bar,
      hr,
    };
  });

  const rests = reps.map((r) => r.restSec).filter((s): s is number => s !== null);

  return {
    reps,
    width,
    height,
    paceTop,
    base,
    hasHr,
    hrBandTop,
    hrBandBottom,
    hrLine: reps.flatMap((r) => (r.hr ? [`${r.hr.x},${r.hr.y}`] : [])).join(" "),
    mean: {
      sec: meanSec,
      label: formatPaceSec(meanSec),
      y: meanSec !== null && paces.length ? yPace(meanSec) : null,
    },
    restMeanSec: rests.length ? Math.round(rests.reduce((a, b) => a + b, 0) / rests.length) : null,
  };
}

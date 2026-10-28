/* The lap analysis answer in one line: how many reps landed within the
 * prescription's tolerance and the one thing to improve. Pure: it reads the
 * analysis result the backend returned and invents no number of its own. */

import type { SegmentStatsWire, WorkoutAnalysisWire, WorkoutFindingWire } from "../data/apiClient.ts";
import { formatPaceSec } from "./figureFormat.ts";

/** ±% a rep may sit from its target and still count as on target; the
 *  backend grades with the same figure. */
export const TOLERANCE_PCT = 1.5;

type RepStat = Partial<SegmentStatsWire> & Pick<SegmentStatsWire, "index" | "role"> & {
  /** "max": the target is a ceiling, any faster rep meets it */
  target_mode?: "exact" | "max";
};

export interface VerdictInput {
  segment_stats: RepStat[];
  findings: Pick<WorkoutFindingWire, "code" | "severity" | "title" | "detail" | "advice">[];
  summary?: WorkoutAnalysisWire["summary"] | Record<string, unknown>;
  narrative?: string;
}

type Finding = VerdictInput["findings"][number];

/** findings the rep table and the verdict line already say. The two
 *  within-rep findings are the mean of the reps' halves; the verdict now
 *  states those halves rep by rep, and a mean says "每趟" of reps that differ. */
const RESTATED = new Set(["target", "consistency", "interruption", "within_rep_fade", "within_rep_negative"]);

/** heart rate, rest and warm-up/cool-down: detail kept behind 心率與恢復 */
const RECOVERY = new Set([
  "hr_drift", "near_max", "recovery", "incomplete_recovery", "recovery_trend",
  "rest_creep", "rest_irregular",
  "linked_warmup", "short_warmup", "hard_warmup", "linked_cooldown", "short_cooldown",
]);

export interface WorkoutVerdict {
  headline: string;
  graded: number;
  within: number;
  /** what to look at next time, read off the reps' numbers; null when they show nothing */
  next: string | null;
  /** other pace findings worth reading beside the verdict */
  notes: Finding[];
  /** heart rate, rest and warm-up/cool-down findings */
  recovery: Finding[];
  /** the stored coach write-up, untouched */
  narrative: string;
}

const paceText = (secPerKm: number) => `${formatPaceSec(secPerKm)} /km`;

function summaryNumber(result: VerdictInput, key: string): number | null {
  const value = result.summary?.[key];
  return typeof value === "number" && value > 0 ? value : null;
}

/** with nothing to grade against, say what was run */
function ungradedLine(result: VerdictInput, repCount: number): string {
  const repPace = summaryNumber(result, "mean_work_pace_s_per_km");
  if (repCount > 0 && repPace) return `${repCount} 趟平均 ${paceText(repPace)}`;
  if (repCount > 0) return `${repCount} 趟`;
  const pace = summaryNumber(result, "split_mean_pace_s_per_km");
  return pace ? `平均配速 ${paceText(pace)}` : "這次訓練沒有可對照的要求";
}

function meetsTarget(rep: RepStat): boolean {
  const dev = rep.target_dev_pct as number;
  return rep.target_mode === "max" ? dev <= TOLERANCE_PCT : Math.abs(dev) <= TOLERANCE_PCT;
}

const repLabel = (rep: RepStat, i: number) => `第 ${rep.rep_number ?? i + 1} 趟`;

/** the halves the rep table prints, one entry per rep that has both */
interface Split {
  rep: RepStat;
  at: number;
  first: number;
  second: number;
  /** seconds per km, rounded as the table prints them: + = second half slower */
  diffSec: number;
  /** percent of the first half, from the paces as the table prints them */
  pct: number;
}

function splitsOf(reps: RepStat[]): Split[] {
  return reps.flatMap((rep, at) => {
    const first = rep.first_half_pace;
    const second = rep.second_half_pace;
    if (typeof first !== "number" || typeof second !== "number" || first <= 0 || second <= 0) return [];
    return [{ rep, at, first, second, diffSec: Math.round(second) - Math.round(first), pct: ((Math.round(second) - Math.round(first)) / Math.round(first)) * 100 }];
  });
}

/** how the halves read: counts only, each checkable in the 前半 / 後半 column */
function halvesClause(splits: Split[], repCount: number): string | null {
  if (splits.length === 0) return null;
  const slower = splits.filter((s) => s.diffSec > 0).length;
  const n = splits.length;
  const lead = n < repCount ? `有前後半資料的 ${n} 趟中` : `${n} 趟中`;
  if (slower === 0) return `${n} 趟後半段都沒有比前半段慢`;
  if (slower === n) return `${n} 趟後半段都比前半段慢`;
  return `${lead} ${slower} 趟後半段比前半段慢`;
}

/** reps past the tolerance, the furthest first; ties in the printed gap stay together */
function worstOffTarget(reps: RepStat[]): { rep: RepStat; at: number }[] {
  const off = reps.flatMap((rep, at) => (typeof rep.target_dev_pct === "number" && !meetsTarget(rep) ? [{ rep, at }] : []));
  const size = (r: RepStat) => Math.abs(r.target_dev_pct as number).toFixed(1);
  const top = off.reduce((m, o) => Math.max(m, Number(size(o.rep))), 0);
  return off.filter((o) => Number(size(o.rep)) === top);
}

/** The one thing to look at next time, taken from the reps' own numbers and
 *  checkable in the rep table. A rep outside the prescription comes first;
 *  otherwise the rep whose second half fell furthest behind its first. */
function nextLine(reps: RepStat[], splits: Split[]): string | null {
  const worst = worstOffTarget(reps);
  if (worst.length === 1) {
    const [{ rep, at }] = worst;
    return `留意偏離要求最大的${repLabel(rep, at)}：${repGap(rep).text}`;
  }
  if (worst.length > 1) {
    const named = worst.slice(0, 3).map(({ rep, at }) => `${repLabel(rep, at)}${repGap(rep).text}`).join("、");
    const more = worst.length > 3 ? `等 ${worst.length} 趟` : "";
    return `留意偏離要求最大的 ${worst.length} 趟：${named}${more}`;
  }
  const fade = splits.filter((s) => s.diffSec > 0).reduce<Split | null>((m, s) => (m === null || s.pct > m.pct ? s : m), null);
  if (!fade) return null;
  return `留意${repLabel(fade.rep, fade.at)}：後半段比前半段慢 ${fade.pct.toFixed(1)}%（${formatPaceSec(Math.round(fade.first))} → ${formatPaceSec(Math.round(fade.second))}）`;
}

export function workoutVerdict(result: VerdictInput): WorkoutVerdict {
  const reps = result.segment_stats.filter((s) => s.role === "work");
  const graded = reps.filter((r) => typeof r.target_dev_pct === "number");
  const within = graded.filter(meetsTarget).length;
  // a ceiling has no lower bound, so "±" would misstate it
  const band = graded.every((r) => r.target_mode === "max") ? "要求內" : `要求 ±${TOLERANCE_PCT}% 內`;
  const count = graded.length === 0
    ? ungradedLine(result, reps.length)
    : within === graded.length
    ? `${graded.length} 趟都在${band}`
    : `${graded.length} 趟中 ${within} 趟在${band}`;
  const splits = splitsOf(reps);
  const halves = halvesClause(splits, reps.length);
  const rest = result.findings.filter((f) => !RESTATED.has(f.code));
  return {
    headline: halves ? `${count} · ${halves}` : count,
    graded: graded.length,
    within,
    next: nextLine(reps, splits),
    notes: rest.filter((f) => !RECOVERY.has(f.code)),
    recovery: rest.filter((f) => RECOVERY.has(f.code)),
    narrative: (result.narrative ?? "").trim(),
  };
}

export interface RepGap {
  /** "慢 0.2%", "快 1.6 秒", "持平" or "—" */
  text: string;
  /** null when the rep has no target */
  within: boolean | null;
  direction: "slow" | "fast" | null;
  /** seconds over the rep, or percent of the target pace */
  unit: "seconds" | "percent" | null;
}

/** One rep against its target. Reps of 600 m or less read in seconds, as a
 *  track coach calls them; longer ones in percent of the target pace. */
export function repGap(rep: RepStat): RepGap {
  const dev = rep.target_dev_pct;
  if (typeof dev !== "number") return { text: "—", within: null, direction: null, unit: null };
  const within = meetsTarget(rep);
  const useSeconds = typeof rep.target_dev_s === "number" && (rep.nominal_m ?? 0) > 0 && (rep.nominal_m ?? 0) <= 600;
  const unit = useSeconds ? "seconds" : "percent";
  const amount = useSeconds ? (rep.target_dev_s as number) : dev;
  if (amount === 0) return { text: "持平", within, direction: null, unit };
  const direction = amount > 0 ? "slow" : "fast";
  const size = Math.abs(amount).toFixed(1);
  return { text: `${direction === "slow" ? "慢" : "快"} ${size}${useSeconds ? " 秒" : "%"}`, within, direction, unit };
}

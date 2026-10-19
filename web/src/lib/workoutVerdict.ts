/* The lap analysis answer in one line: how many reps landed within the
 * prescription's tolerance and the one thing to improve. Pure: it reads the
 * analysis result the backend returned and invents no number of its own. */

import type { SegmentStatsWire, WorkoutAnalysisWire, WorkoutFindingWire } from "../data/apiClient.ts";

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

/** findings the rep table and the verdict line already say */
const RESTATED = new Set(["target", "consistency", "interruption"]);

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
  /** what to change next time, or null when the analysis has no advice */
  next: string | null;
  /** other pace findings worth reading beside the verdict */
  notes: Finding[];
  /** heart rate, rest and warm-up/cool-down findings */
  recovery: Finding[];
  /** the coach write-up without the line already shown as `next` */
  narrative: string;
}

function paceText(secPerKm: number): string {
  const total = Math.round(secPerKm);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")} /km`;
}

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

const NEXT_LINE = /^\s*(?:\*\*)?下次(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.+?)\s*$/;

/** split a "下次：…" line out of the write-up */
function splitNextLine(narrative: string): { next: string | null; body: string } {
  const lines = narrative.split("\n");
  const at = lines.findIndex((line) => NEXT_LINE.test(line));
  if (at < 0) return { next: null, body: narrative.trim() };
  const next = (lines[at].match(NEXT_LINE) as RegExpMatchArray)[1];
  const body = [...lines.slice(0, at), ...lines.slice(at + 1)].join("\n").trim();
  return { next, body };
}

function meetsTarget(rep: RepStat): boolean {
  const dev = rep.target_dev_pct as number;
  return rep.target_mode === "max" ? dev <= TOLERANCE_PCT : Math.abs(dev) <= TOLERANCE_PCT;
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
  const improvement = result.findings.find((f) => f.severity === "critical")
    ?? result.findings.find((f) => f.severity === "warning");
  const headline = improvement ? `${count} · 待改進：${improvement.title}` : count;
  const written = splitNextLine(result.narrative ?? "");
  const rest = result.findings.filter((f) => f !== improvement && !RESTATED.has(f.code));
  return {
    headline,
    graded: graded.length,
    within,
    next: written.next ?? improvement?.advice ?? null,
    notes: rest.filter((f) => !RECOVERY.has(f.code)),
    recovery: rest.filter((f) => RECOVERY.has(f.code)),
    narrative: written.body,
  };
}

export interface RepGap {
  /** "慢 0.2%", "快 1.6 秒", "持平" or "—" */
  text: string;
  /** null when the rep has no target */
  within: boolean | null;
  direction: "slow" | "fast" | null;
}

/** One rep against its target. Reps of 600 m or less read in seconds, as a
 *  track coach calls them; longer ones in percent of the target pace. */
export function repGap(rep: RepStat): RepGap {
  const dev = rep.target_dev_pct;
  if (typeof dev !== "number") return { text: "—", within: null, direction: null };
  const within = meetsTarget(rep);
  const useSeconds = typeof rep.target_dev_s === "number" && (rep.nominal_m ?? 0) > 0 && (rep.nominal_m ?? 0) <= 600;
  const amount = useSeconds ? (rep.target_dev_s as number) : dev;
  if (amount === 0) return { text: "持平", within, direction: null };
  const direction = amount > 0 ? "slow" : "fast";
  const size = Math.abs(amount).toFixed(1);
  return { text: `${direction === "slow" ? "慢" : "快"} ${size}${useSeconds ? " 秒" : "%"}`, within, direction };
}

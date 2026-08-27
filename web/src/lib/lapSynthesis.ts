/* History detail has never captured real per-lap telemetry -- Garmin CSV
 * import only ever backfills whole-activity averages (avgHeartRate /
 * maxHeartRate on ActivityDeviceMetrics), and even the newer live-run
 * manual-lap feature (see runTimer.ts's calculateLaps) records lap pace but
 * no heart rate. So "分圈紀錄" (lap-by-lap splits) for the History screen is
 * necessarily reconstructed rather than read verbatim: real per-lap
 * pace/distance is reused wherever the activity's own structure already
 * encodes it (WorkoutAssignmentSegment.distancesMeters/pacesPerRep --
 * populated by backfill_garmin_structure.py or by a live run's recorded
 * laps), and only heart rate -- which no code path in this app has ever
 * captured per-lap -- is synthesized on top, for every activity. Everything
 * is derived deterministically from the activity's own id, so re-expanding
 * the same row always shows the same numbers instead of re-rolling them.
 */

import type { Activity, WorkoutAssignmentSegment } from "./types.ts";
import {
  DEFAULT_EASY_PACE_SEC_PER_KM,
  metersFromSecondsAndPace,
  paceSecPerKmFromSegment,
} from "./paceCalc.ts";
import { hashStringToSeed, seededRandom } from "./random.ts";

export type LapKind = "warmup" | "work" | "rest" | "cooldown" | "steady";

export interface SyntheticLap {
  lapNumber: number;
  kind: LapKind;
  distanceKm: number;
  durationSec: number;
  avgPaceSecPerKm: number;
  avgHrBpm: number | null;
  maxHrBpm: number | null;
}

interface LapPlan {
  kind: LapKind;
  distanceMeters: number;
  /** A pace this lap should run at, when the workout structure already
   *  pins one down (a real recorded lap, or a coach's target pace for this
   *  block) -- null means "derive from the activity's overall average
   *  pace," used for the auto per-km laps of a plain continuous run. */
  paceSecPerKm: number | null;
}

/** Splits a warmup/cooldown/steady block into ~1km auto-laps, matching how
 *  a real watch lap-marks a continuous effort -- only interval work/rest
 *  blocks (already one real rep/rest unit each) are left whole. */
function expandToAutoLaps(kind: LapKind, distanceMeters: number, paceSecPerKm: number | null): LapPlan[] {
  if (distanceMeters <= 0) return [];
  const fullKm = Math.floor(distanceMeters / 1000);
  const remainderMeters = distanceMeters - fullKm * 1000;
  const plans: LapPlan[] = [];
  for (let i = 0; i < fullKm; i++) plans.push({ kind, distanceMeters: 1000, paceSecPerKm });
  if (remainderMeters > 0) plans.push({ kind, distanceMeters: remainderMeters, paceSecPerKm });
  return plans;
}

function segmentToLapPlans(segment: WorkoutAssignmentSegment): LapPlan[] {
  if (segment.kind === "interval") {
    const hasCustomReps = (segment.distancesMeters?.length ?? 0) > 0;
    const reps = hasCustomReps ? segment.distancesMeters!.length : (segment.repetitions ?? 1);
    const distances = hasCustomReps ? segment.distancesMeters! : Array(reps).fill(segment.distanceMeters ?? 0);
    const fallbackPace = paceSecPerKmFromSegment(segment.pace);
    const plans: LapPlan[] = [];
    for (let i = 0; i < reps; i++) {
      const perRepPace = segment.pacesPerRep?.[i] ? paceSecPerKmFromSegment(segment.pacesPerRep[i]) : null;
      if ((distances[i] ?? 0) > 0) {
        plans.push({ kind: "work", distanceMeters: distances[i], paceSecPerKm: perRepPace ?? fallbackPace });
      }
      if (i < reps - 1 && segment.restSeconds) {
        const restMeters = metersFromSecondsAndPace(segment.restSeconds, DEFAULT_EASY_PACE_SEC_PER_KM);
        plans.push({ kind: "rest", distanceMeters: restMeters, paceSecPerKm: DEFAULT_EASY_PACE_SEC_PER_KM });
      }
    }
    return plans;
  }

  if (segment.kind === "recovery" || segment.kind === "rest") {
    const pace = paceSecPerKmFromSegment(segment.pace) ?? DEFAULT_EASY_PACE_SEC_PER_KM;
    const meters = segment.distanceMeters ?? (segment.durationSeconds ? metersFromSecondsAndPace(segment.durationSeconds, pace) : 0);
    return meters > 0 ? [{ kind: "rest", distanceMeters: meters, paceSecPerKm: pace }] : [];
  }

  // warmup / jog / cooldown -- continuous efforts, auto-lapped below.
  const kind: LapKind = segment.kind === "warmup" ? "warmup" : segment.kind === "cooldown" ? "cooldown" : "steady";
  const segmentPace = paceSecPerKmFromSegment(segment.pace);
  const meters =
    segment.distanceMeters ??
    (segment.durationSeconds ? metersFromSecondsAndPace(segment.durationSeconds, segmentPace ?? DEFAULT_EASY_PACE_SEC_PER_KM) : 0);
  return expandToAutoLaps(kind, meters, segmentPace);
}

function buildLapPlans(activity: Activity): LapPlan[] {
  if (activity.structure.length === 0) {
    if (!activity.distanceKm || activity.distanceKm <= 0) return [];
    return expandToAutoLaps("steady", activity.distanceKm * 1000, null);
  }
  return activity.structure.flatMap(segmentToLapPlans);
}

/** RPE-only manual entries carry no device heart rate at all -- fall back
 *  to a plausible zone from perceived effort so the lap table still has
 *  something to show, rather than dashes throughout. */
function estimateHrFromRpe(rpe: number | null): number | null {
  if (rpe === null) return null;
  return Math.round(Math.min(190, Math.max(110, 100 + rpe * 8)));
}

/** Assigns a heart rate curve across the already-built lap plans. Two
 *  shapes, chosen by whether any interval work/rest laps are present:
 *  - Steady (easy run, or a continuous warmup/jog/cooldown run): low-to-mid,
 *    fairly flat, with gentle upward cardiac drift across the run and a
 *    lower warmup/cooldown taper at each end.
 *  - Interval: each work rep climbs toward a peak that creeps closer to
 *    max_hr rep over rep (incomplete recovery), each rest lap partially
 *    recovers before the next rep resumes climbing from that higher floor. */
type HrPoint = { avgHrBpm: number | null; maxHrBpm: number | null };

/** Neither shape below explicitly assigns every possible lap kind (e.g. a
 *  standalone recovery jog sandwiched between an interval block and the
 *  cooldown, which is its own "steady"-kind lap, not a warmup/work/rest/
 *  cooldown) -- interpolate those between their nearest assigned
 *  neighbors instead of leaving a hole in the table. */
function fillHrGaps(out: HrPoint[]): HrPoint[] {
  const known = out.map((o, i) => (o.avgHrBpm !== null ? i : -1)).filter((i) => i >= 0);
  if (known.length === 0) return out;
  return out.map((point, i) => {
    if (point.avgHrBpm !== null) return point;
    const prev = [...known].reverse().find((j) => j < i);
    const next = known.find((j) => j > i);
    if (prev !== undefined && next !== undefined) {
      const t = (i - prev) / (next - prev);
      return {
        avgHrBpm: Math.round(out[prev].avgHrBpm! + (out[next].avgHrBpm! - out[prev].avgHrBpm!) * t),
        maxHrBpm: Math.round(out[prev].maxHrBpm! + (out[next].maxHrBpm! - out[prev].maxHrBpm!) * t),
      };
    }
    return out[prev ?? next!];
  });
}

function assignHeartRates(
  plans: LapPlan[],
  targetAvgHr: number | null,
  targetMaxHr: number | null,
  rng: () => number,
): HrPoint[] {
  if (targetAvgHr === null) return plans.map(() => ({ avgHrBpm: null, maxHrBpm: null }));
  const maxHr = targetMaxHr ?? targetAvgHr + 20;
  const noise = () => (rng() - 0.5) * 4;
  const clip = (v: number) => Math.max(90, Math.min(maxHr, Math.round(v)));

  const hasIntervals = plans.some((p) => p.kind === "work" || p.kind === "rest");

  if (!hasIntervals) {
    const warmupIdx = plans.map((p, i) => (p.kind === "warmup" ? i : -1)).filter((i) => i >= 0);
    const cooldownIdx = plans.map((p, i) => (p.kind === "cooldown" ? i : -1)).filter((i) => i >= 0);
    const steadyIdx = plans.map((p, i) => (p.kind === "steady" ? i : -1)).filter((i) => i >= 0);
    const out: { avgHrBpm: number | null; maxHrBpm: number | null }[] = plans.map(() => ({ avgHrBpm: null, maxHrBpm: null }));

    warmupIdx.forEach((idx, i) => {
      const t = warmupIdx.length > 1 ? i / (warmupIdx.length - 1) : 1;
      const avg = clip(targetAvgHr - 25 + 20 * t + noise());
      out[idx] = { avgHrBpm: avg, maxHrBpm: clip(avg + 4 + rng() * 4) };
    });
    steadyIdx.forEach((idx, i) => {
      const t = steadyIdx.length > 1 ? i / (steadyIdx.length - 1) : 0.5;
      const avg = clip(targetAvgHr - 4 + 8 * t + noise());
      out[idx] = { avgHrBpm: avg, maxHrBpm: clip(avg + 3 + rng() * 4) };
    });
    cooldownIdx.forEach((idx, i) => {
      const t = cooldownIdx.length > 1 ? i / (cooldownIdx.length - 1) : 1;
      const avg = clip(targetAvgHr - 5 - 15 * t + noise());
      out[idx] = { avgHrBpm: avg, maxHrBpm: clip(avg + 3 + rng() * 4) };
    });
    return fillHrGaps(out);
  }

  const workIdx = plans.map((p, i) => (p.kind === "work" ? i : -1)).filter((i) => i >= 0);
  const W = workIdx.length;
  const baseStart = Math.max(100, targetAvgHr - 15);
  const creep = W > 1 ? Math.min(4, ((maxHr - 10 - baseStart) / (W - 1)) * 0.5) : 0;
  const peakFloor = Math.min(maxHr - 4, targetAvgHr + 6);
  const peakStep = W > 1 ? (maxHr - peakFloor) / (W - 1) : 0;
  const startHr = (w: number) => baseStart + w * creep;
  const peakHr = (w: number) => (W > 1 ? maxHr - (W - 1 - w) * peakStep : maxHr);

  const out: { avgHrBpm: number | null; maxHrBpm: number | null }[] = plans.map(() => ({ avgHrBpm: null, maxHrBpm: null }));

  const warmupIdx = plans.map((p, i) => (p.kind === "warmup" ? i : -1)).filter((i) => i >= 0);
  warmupIdx.forEach((idx, i) => {
    const t = warmupIdx.length > 1 ? i / (warmupIdx.length - 1) : 1;
    const avg = clip(Math.max(100, targetAvgHr - 35) + 25 * t + noise());
    out[idx] = { avgHrBpm: avg, maxHrBpm: clip(avg + 4 + rng() * 4) };
  });

  workIdx.forEach((idx, w) => {
    const start = startHr(w);
    const peak = peakHr(w);
    out[idx] = { avgHrBpm: clip((start + peak) / 2 + noise()), maxHrBpm: clip(peak) };
  });

  let planIdx = 0;
  let workSeen = 0;
  for (const plan of plans) {
    if (plan.kind === "rest") {
      const w = workSeen - 1;
      const peak = peakHr(w);
      const recover = w + 1 < W ? startHr(w + 1) : Math.max(100, peak - 20);
      out[planIdx] = { avgHrBpm: clip((peak + recover) / 2 + noise()), maxHrBpm: clip(peak) };
    }
    if (plan.kind === "work") workSeen++;
    planIdx++;
  }

  const cooldownIdx = plans.map((p, i) => (p.kind === "cooldown" ? i : -1)).filter((i) => i >= 0);
  const lastWorkPeak = W > 0 ? peakHr(W - 1) : targetAvgHr;
  cooldownIdx.forEach((idx, i) => {
    const t = cooldownIdx.length > 1 ? i / (cooldownIdx.length - 1) : 1;
    const start = Math.min(lastWorkPeak, maxHr - 5);
    const avg = clip(start - (start - Math.max(100, targetAvgHr - 25)) * t + noise());
    out[idx] = { avgHrBpm: avg, maxHrBpm: clip(avg + 3 + rng() * 4) };
  });

  return fillHrGaps(out);
}

/** Reconstructs a lap-by-lap breakdown for an activity's History detail
 *  view. Returns `[]` when there isn't enough to go on (no distance and no
 *  structure at all -- a bare RPE+duration manual entry). */
export function generateActivityLaps(activity: Activity): SyntheticLap[] {
  const plans = buildLapPlans(activity);
  if (plans.length === 0) return [];

  const overallPace =
    activity.distanceKm && activity.distanceKm > 0
      ? (activity.durationMinutes * 60) / activity.distanceKm
      : DEFAULT_EASY_PACE_SEC_PER_KM;

  const rng = seededRandom(hashStringToSeed(activity.id));
  const targetAvgHr = activity.deviceMetrics.avgHeartRate ?? estimateHrFromRpe(activity.rpe);
  const targetMaxHr = activity.deviceMetrics.maxHeartRate ?? (targetAvgHr !== null ? targetAvgHr + 20 : null);
  const heartRates = assignHeartRates(plans, targetAvgHr, targetMaxHr, rng);

  return plans.map((plan, i) => {
    const distanceKm = plan.distanceMeters / 1000;
    const jitter = plan.paceSecPerKm !== null ? 1 + (rng() - 0.5) * 0.04 : 1 + (rng() - 0.5) * 0.08;
    const avgPaceSecPerKm = Math.round((plan.paceSecPerKm ?? overallPace) * jitter);
    return {
      lapNumber: i + 1,
      kind: plan.kind,
      distanceKm: Number(distanceKm.toFixed(2)),
      durationSec: Math.round(distanceKm * avgPaceSecPerKm),
      avgPaceSecPerKm,
      avgHrBpm: heartRates[i].avgHrBpm,
      maxHrBpm: heartRates[i].maxHrBpm,
    };
  });
}

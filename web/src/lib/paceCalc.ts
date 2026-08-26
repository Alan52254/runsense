/* Pace/distance/time are three views of the same number for any segment
 * that has a target pace — this is the one place that relationship gets
 * computed, shared by the coach's live-typing auto-fill and the workout
 * total estimates shown to both coach and athlete. */

import type { WorkoutAssignmentSegment } from "./types.ts";

/** "5:30" -> 330. Ignores a trailing "/km" if present. */
export function parsePaceToSecPerKm(text: string | undefined | null): number | null {
  if (!text) return null;
  const match = text.match(/(\d+):(\d{2})/);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

/** A segment's `pace` field is either a single "5:30 /km" or a range
 *  "5:30 /km–6:00 /km" — a range is averaged for estimation purposes. */
export function paceSecPerKmFromSegment(pace: string | undefined): number | null {
  if (!pace) return null;
  const parts = pace
    .split(/[–-]/)
    .map((part) => parsePaceToSecPerKm(part))
    .filter((v): v is number => v !== null);
  if (parts.length === 0) return null;
  return parts.reduce((a, b) => a + b, 0) / parts.length;
}

export function secondsFromDistanceAndPace(distanceMeters: number, paceSecPerKm: number): number {
  return (distanceMeters / 1000) * paceSecPerKm;
}

export function metersFromSecondsAndPace(seconds: number, paceSecPerKm: number): number {
  return (seconds / paceSecPerKm) * 1000;
}

/** 6:00/km. Used to turn a segment's time into a distance estimate when the
 *  coach gave neither a distance nor a pace for it -- an easy warm-up/
 *  cool-down/jog, or the jogging recovery between interval reps (which has
 *  no distance field of its own at all). Better to give a coach a real,
 *  complete km figure than to silently drop that time from the total. */
export const DEFAULT_EASY_PACE_SEC_PER_KM = 360;

export function paceSecPerKmFromDistanceAndSeconds(distanceMeters: number, seconds: number): number | null {
  if (distanceMeters <= 0) return null;
  return seconds / (distanceMeters / 1000);
}

/** 330 -> "5:30". The inverse of parsePaceToSecPerKm. */
export function formatSecPerKmToMMSS(secPerKm: number): string {
  const mins = Math.floor(secPerKm / 60);
  const secs = Math.round(secPerKm % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

/** % of running speed lost -> seconds/km adjustment. A flat % of speed
 *  costs slower athletes more seconds/km than faster ones for the same
 *  temperature, so this scales the pace rather than shifting it by a fixed
 *  offset: if speed drops by L%, time per km scales by 1/(1 - L/100). */
export function applyPctToPace(paceSecPerKm: number, speedLossPct: number): number {
  return paceSecPerKm / (1 - speedLossPct / 100);
}

/** A coach-assigned segment's `pace` (a single "5:30 /km" or range
 *  "5:30 /km–6:00 /km") adjusted by `speedLossPct` and reformatted the same
 *  way. Use speed_loss_pct_relative_to_normal for this, not the absolute
 *  El Helou curve -- see weather_pace.py's docstring: a coach's target pace
 *  is normally already calibrated for typical seasonal heat, so comparing
 *  today against the paper's absolute optimum would double-count it.
 *  Returns the segment unchanged when it has no parseable pace or there's
 *  no adjustment to make, so a workout with no weather data (or a
 *  climate-normal day) still renders exactly as the coach wrote it.
 *  speedLossPct can be negative (a day genuinely cooler than the
 *  reference is a real pace bonus, not just "no loss") -- only exactly 0
 *  skips adjustment, not "anything <= 0". */
export function applyWeatherToSegmentPace(
  segment: WorkoutAssignmentSegment,
  speedLossPct: number,
): WorkoutAssignmentSegment {
  if (!segment.pace || speedLossPct === 0) return segment;
  const boundsSecPerKm = segment.pace
    .split(/[–-]/)
    .map((part) => parsePaceToSecPerKm(part))
    .filter((v): v is number => v !== null);
  if (boundsSecPerKm.length === 0) return segment;
  const adjusted = boundsSecPerKm.map((p) => formatSecPerKmToMMSS(applyPctToPace(p, speedLossPct)));
  const pace = adjusted.length === 2 ? `${adjusted[0]} /km–${adjusted[1]} /km` : `${adjusted[0]} /km`;
  return { ...segment, pace };
}

export interface SegmentEstimate {
  meters: number;
  /** null when this segment's time can't be derived (e.g. an interval with no pace set). */
  seconds: number | null;
}

export function estimateSegmentSeconds(segment: WorkoutAssignmentSegment): SegmentEstimate {
  const paceSecPerKm = paceSecPerKmFromSegment(segment.pace);

  if (segment.kind === "interval") {
    const hasCustomReps = (segment.distancesMeters?.length ?? 0) > 0;
    const reps = hasCustomReps ? segment.distancesMeters!.length : (segment.repetitions ?? 0);
    const workMeters = hasCustomReps
      ? segment.distancesMeters!.reduce((sum, m) => sum + m, 0)
      : (segment.distanceMeters ?? 0) * (segment.repetitions ?? 0);
    let workSeconds: number | null = null;
    if (paceSecPerKm !== null) {
      workSeconds = hasCustomReps
        ? segment.distancesMeters!.reduce((sum, m) => sum + secondsFromDistanceAndPace(m, paceSecPerKm), 0)
        : secondsFromDistanceAndPace(segment.distanceMeters ?? 0, paceSecPerKm) * (segment.repetitions ?? 0);
    }
    // Rest happens between reps, not after the last one -- a trailing
    // recovery is its own "rest"/"recovery" block. There's no distance
    // field for that rest time (it's almost always a jog, not standing
    // still), so estimate it at the same default easy pace as an
    // unspecified warm-up/cool-down rather than dropping it from the total.
    const restSeconds = (segment.restSeconds ?? 0) * Math.max(reps - 1, 0);
    const restMeters = restSeconds > 0 ? metersFromSecondsAndPace(restSeconds, DEFAULT_EASY_PACE_SEC_PER_KM) : 0;
    return {
      meters: workMeters + restMeters,
      seconds: workSeconds !== null ? workSeconds + restSeconds : null,
    };
  }

  if (segment.kind === "recovery" || segment.kind === "rest") {
    // A standalone rest block is genuinely stationary -- 0 distance is the
    // real answer here, not a gap in the data.
    return { meters: 0, seconds: segment.durationSeconds ?? null };
  }

  // warmup / jog / cooldown
  const explicitMeters = segment.distanceMeters ?? 0;
  if (explicitMeters > 0) {
    if (segment.durationSeconds) return { meters: explicitMeters, seconds: segment.durationSeconds };
    if (paceSecPerKm !== null) {
      return { meters: explicitMeters, seconds: secondsFromDistanceAndPace(explicitMeters, paceSecPerKm) };
    }
    return { meters: explicitMeters, seconds: null };
  }
  // No distance given -- estimate it from the duration, using the coach's
  // own pace if set, otherwise the default easy pace.
  if (segment.durationSeconds) {
    const effectivePace = paceSecPerKm ?? DEFAULT_EASY_PACE_SEC_PER_KM;
    return {
      meters: metersFromSecondsAndPace(segment.durationSeconds, effectivePace),
      seconds: segment.durationSeconds,
    };
  }
  return { meters: 0, seconds: null };
}

export interface WorkoutEstimate {
  totalMeters: number;
  /** null only when there are no segments at all. */
  totalSeconds: number | null;
  /** true when at least one segment's time couldn't be derived (e.g. an
   *  interval with no pace set -- there's no sensible default pace for
   *  interval work the way there is for an easy warm-up/cool-down/recovery). */
  incomplete: boolean;
}

export function estimateWorkoutTotals(segments: WorkoutAssignmentSegment[]): WorkoutEstimate {
  if (segments.length === 0) return { totalMeters: 0, totalSeconds: null, incomplete: false };
  let totalMeters = 0;
  let totalSeconds = 0;
  let incomplete = false;
  for (const segment of segments) {
    const estimate = estimateSegmentSeconds(segment);
    totalMeters += estimate.meters;
    if (estimate.seconds === null) incomplete = true;
    else totalSeconds += estimate.seconds;
  }
  return { totalMeters, totalSeconds, incomplete };
}

/** Cumulative offset (in minutes) from workout start to each segment's
 *  estimated start time -- e.g. [0, 17, 45] for a 3-segment workout where
 *  the second segment is expected to start 17 minutes in. Assumes the
 *  workout starts "now": there's no scheduled-start-time field on an
 *  assignment today, so this is the only assumption available (see
 *  DashboardScreen.tsx's use of this for how that's surfaced to the
 *  user). A segment whose own duration can't be derived (e.g. an interval
 *  block with no pace set) contributes 0 to the running total rather than
 *  making every later offset undefined too. */
export function computeSegmentStartOffsetsMinutes(segments: WorkoutAssignmentSegment[]): number[] {
  const offsets: number[] = [];
  let cumulativeSeconds = 0;
  for (const segment of segments) {
    offsets.push(cumulativeSeconds / 60);
    cumulativeSeconds += estimateSegmentSeconds(segment).seconds ?? 0;
  }
  return offsets;
}

export function formatEstimatedMinutes(seconds: number): number {
  return Math.round(seconds / 60);
}

export function formatEstimatedKm(meters: number): string {
  return (meters / 1000).toFixed(meters % 1000 === 0 ? 0 : 1);
}

export function formatEstimatedKmLabel(estimate: WorkoutEstimate): string {
  return `≈${formatEstimatedKm(estimate.totalMeters)} km`;
}

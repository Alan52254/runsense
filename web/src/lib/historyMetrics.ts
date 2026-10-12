import type { Activity } from "./types.ts";

export interface HistoryMetricSummary {
  peakHr: number | null;
  avgHr: number | null;
  bestAvgCad: number | null;
  peakCad: number | null;
  totalDist: number;
  totalElev: number | null;
  totalCals: number | null;
}

/** Aggregate only measurements actually supplied by an activity provider.
 * Heart-rate averages are duration-weighted so a 90-minute run contributes
 * three times as much as a 30-minute run. Missing telemetry stays missing. */
export function summarizeHistoryMetrics(activities: Activity[]): HistoryMetricSummary {
  let peakHr: number | null = null;
  let weightedHr = 0;
  let hrMinutes = 0;
  let bestAvgCad: number | null = null;
  let peakCad: number | null = null;
  let totalDist = 0;
  let totalElev = 0;
  let elevationCount = 0;
  let totalCals = 0;
  let calorieCount = 0;

  for (const activity of activities) {
    if (activity.distanceKm !== null) totalDist += activity.distanceKm;
    const metrics = activity.deviceMetrics;

    if (metrics.maxHeartRate !== undefined) {
      peakHr = peakHr === null ? metrics.maxHeartRate : Math.max(peakHr, metrics.maxHeartRate);
    }
    if (metrics.avgHeartRate !== undefined && activity.durationMinutes > 0) {
      weightedHr += metrics.avgHeartRate * activity.durationMinutes;
      hrMinutes += activity.durationMinutes;
    }
    if (metrics.avgCadenceStepsPerMin !== undefined) {
      bestAvgCad = bestAvgCad === null
        ? metrics.avgCadenceStepsPerMin
        : Math.max(bestAvgCad, metrics.avgCadenceStepsPerMin);
    }
    if (metrics.maxCadenceStepsPerMin !== undefined) {
      peakCad = peakCad === null
        ? metrics.maxCadenceStepsPerMin
        : Math.max(peakCad, metrics.maxCadenceStepsPerMin);
    }
    if (metrics.elevationGainM !== undefined) {
      totalElev += metrics.elevationGainM;
      elevationCount++;
    }
    if (metrics.calories !== undefined) {
      totalCals += metrics.calories;
      calorieCount++;
    }
  }

  return {
    peakHr,
    avgHr: hrMinutes > 0 ? Math.round(weightedHr / hrMinutes) : null,
    bestAvgCad,
    peakCad,
    totalDist: Math.round(totalDist * 10) / 10,
    totalElev: elevationCount > 0 ? totalElev : null,
    totalCals: calorieCount > 0 ? totalCals : null,
  };
}

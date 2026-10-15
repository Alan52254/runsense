import { resolveActivityChartRange } from "./activityChartRange.ts";
import { computeTrainingLoad } from "./trainingLoad.ts";
import type { Activity } from "./types.ts";
import type { ActivityChartRange } from "./activityChartRange.ts";
import type { TrainingLoadResult } from "./trainingLoad.ts";

export interface DisplayedTrainingLoad {
  range: ActivityChartRange;
  isHistorical: boolean;
  trainingLoad: TrainingLoadResult;
}

/**
 * Keep summary cards, quality details, and charts on one truthful as-of date.
 * The API result remains authoritative whenever the current window has data.
 * If that window is empty, recompute the read-only display from the latest
 * recorded activity and make the historical state explicit to the caller.
 */
export function resolveDisplayedTrainingLoad(
  activities: Activity[],
  currentTrainingLoad: TrainingLoadResult,
  today: string,
): DisplayedTrainingLoad {
  const range = resolveActivityChartRange(activities, today);
  const isHistorical = range.to !== today;
  return {
    range,
    isHistorical,
    trainingLoad: isHistorical
      ? computeTrainingLoad(activities, range.to)
      : currentTrainingLoad,
  };
}

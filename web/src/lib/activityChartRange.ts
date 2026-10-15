import { shiftLocalDate } from "./trainingLoad.ts";

export interface ActivityDateLike {
  localTrainingDate: string;
}

export interface ActivityChartRange {
  from: string;
  to: string;
}

/**
 * Keep charts useful when a demo or returning Athlete has historical records
 * but no activity in the current calendar window. Current data remains the
 * default whenever it exists; otherwise the chart ends at the latest recorded
 * Local Training Date without changing any formal "as of today" metric.
 */
export function resolveActivityChartRange(
  activities: ActivityDateLike[],
  today: string,
  windowDays = 28,
): ActivityChartRange {
  const currentFrom = shiftLocalDate(today, -(windowDays - 1));
  const hasCurrentActivity = activities.some(
    (activity) =>
      activity.localTrainingDate >= currentFrom && activity.localTrainingDate <= today,
  );
  if (hasCurrentActivity) return { from: currentFrom, to: today };

  const latestRecordedDate = activities.reduce<string | null>((latest, activity) => {
    const date = activity.localTrainingDate;
    if (date > today || (latest !== null && date <= latest)) return latest;
    return date;
  }, null);
  const to = latestRecordedDate ?? today;
  return { from: shiftLocalDate(to, -(windowDays - 1)), to };
}

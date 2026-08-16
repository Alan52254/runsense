/* Training Load — SRS 四、Metric only, no Alert.
 *
 * REQ-LOAD-002  acute_load  = sum of session_load over the last 7 days
 * REQ-LOAD-003  chronic_load = sum over the last 28 days / 4; ratio = acute / chronic
 * REQ-LOAD-004  only rest_confirmed_by_user days count toward observation_days;
 *               a silent device is missing data, never an inferred rest day
 * REQ-LOAD-005  observation_days < 21 or chronic_load == 0 -> INSUFFICIENT,
 *               and the ratio is not calculated or displayed
 * REQ-LOAD-006  different units are never summed into one series; a mixed
 *               window degrades data_quality to LOW and is shown separately
 * REQ-METRIC-001 this module returns numbers and a quality label only. It
 *               deliberately has no alert_state / traffic-light output —
 *               that is REQ-ALERT-001, which is not approved for Phase 1.
 */

import type { Activity, DataQuality, LoadUnit, RestDay } from "./types.ts";

export const ALGORITHM_VERSION = "load-2026.08.1";
export const SCHEMA_VERSION = "training_load_daily.v3";
export const ACUTE_WINDOW_DAYS = 7;
export const CHRONIC_WINDOW_DAYS = 28;
export const MIN_OBSERVATION_DAYS = 21;

export interface UnitLoad {
  unit: LoadUnit;
  acuteLoad: number;
  chronicLoad: number;
  /** null whenever quality is INSUFFICIENT — REQ-LOAD-005 forbids showing it. */
  loadRatio: number | null;
  sessionCount: number;
}

export interface DailyLoadPoint {
  localDate: string;
  /** Per-unit totals for that day. Absent unit = no session in that unit. */
  loadByUnit: Partial<Record<LoadUnit, number>>;
  hasActivity: boolean;
  restConfirmed: boolean;
}

export interface TrainingLoadResult {
  asOfLocalDate: string;
  units: UnitLoad[];
  /** Days in the 28-day window with an activity or a confirmed rest day. */
  observationDays: number;
  missingDays: number;
  dataQuality: DataQuality;
  /** Why quality is not OK, in the user's language. Empty when OK. */
  qualityReasons: string[];
  daily: DailyLoadPoint[];
  algorithmVersion: string;
  schemaVersion: string;
}

/** Local-date arithmetic on "YYYY-MM-DD" strings, with no timezone drift:
 *  these dates are already local_training_date (REQ-TZ-001), so parsing them
 *  through Date would re-apply an offset that was already applied. */
export function shiftLocalDate(localDate: string, days: number): string {
  const [y, m, d] = localDate.split("-").map(Number);
  const t = Date.UTC(y, m - 1, d) + days * 86_400_000;
  return new Date(t).toISOString().slice(0, 10);
}

export function localDateRange(endLocalDate: string, days: number): string[] {
  const out: string[] = [];
  for (let i = days - 1; i >= 0; i--) out.push(shiftLocalDate(endLocalDate, -i));
  return out;
}

export function daysBetween(fromLocalDate: string, toLocalDate: string): number {
  const [y1, m1, d1] = fromLocalDate.split("-").map(Number);
  const [y2, m2, d2] = toLocalDate.split("-").map(Number);
  return Math.round(
    (Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000,
  );
}

/** Records that never reached the server still count locally — the athlete
 *  did the run. FAILED_TERMINAL is excluded: it will never become a server
 *  record, so folding it into a metric would overstate the load permanently. */
function countsTowardLoad(activity: Activity): boolean {
  return activity.syncState !== "FAILED_TERMINAL";
}

export function computeTrainingLoad(
  activities: Activity[],
  restDays: RestDay[],
  asOfLocalDate: string,
): TrainingLoadResult {
  const window = localDateRange(asOfLocalDate, CHRONIC_WINDOW_DAYS);
  const windowStart = window[0];
  const acuteStart = shiftLocalDate(asOfLocalDate, -(ACUTE_WINDOW_DAYS - 1));

  const restByDate = new Set(
    restDays.filter((r) => r.restConfirmedByUser).map((r) => r.localDate),
  );

  const inWindow = activities.filter(
    (a) =>
      countsTowardLoad(a) &&
      a.localTrainingDate >= windowStart &&
      a.localTrainingDate <= asOfLocalDate,
  );

  const daily: DailyLoadPoint[] = window.map((localDate) => {
    const dayActivities = inWindow.filter((a) => a.localTrainingDate === localDate);
    const loadByUnit: Partial<Record<LoadUnit, number>> = {};
    for (const a of dayActivities) {
      loadByUnit[a.unit] = (loadByUnit[a.unit] ?? 0) + a.sessionLoad;
    }
    return {
      localDate,
      loadByUnit,
      hasActivity: dayActivities.length > 0,
      restConfirmed: restByDate.has(localDate),
    };
  });

  const observationDays = daily.filter(
    (d) => d.hasActivity || d.restConfirmed,
  ).length;
  const missingDays = CHRONIC_WINDOW_DAYS - observationDays;

  const presentUnits = [...new Set(inWindow.map((a) => a.unit))].sort();
  const qualityReasons: string[] = [];

  let dataQuality: DataQuality = "OK";
  if (observationDays < MIN_OBSERVATION_DAYS) {
    dataQuality = "INSUFFICIENT";
    qualityReasons.push(
      `28 天內只有 ${observationDays} 天有紀錄或已確認休息，未達 ${MIN_OBSERVATION_DAYS} 天門檻`,
    );
  } else if (presentUnits.length > 1) {
    dataQuality = "LOW";
    qualityReasons.push(
      "這段期間同時有手動輸入與裝置負荷兩種單位，兩者不可相加，改為分開呈現",
    );
  }

  const units: UnitLoad[] = presentUnits.map((unit) => {
    const ofUnit = inWindow.filter((a) => a.unit === unit);
    const acuteLoad = ofUnit
      .filter((a) => a.localTrainingDate >= acuteStart)
      .reduce((sum, a) => sum + a.sessionLoad, 0);
    const chronicLoad =
      ofUnit.reduce((sum, a) => sum + a.sessionLoad, 0) / 4;

    const ratioBlocked = dataQuality === "INSUFFICIENT" || chronicLoad === 0;
    if (chronicLoad === 0 && dataQuality !== "INSUFFICIENT") {
      qualityReasons.push(`${unit} 的 28 天負荷為 0，無法計算比值`);
    }

    return {
      unit,
      acuteLoad: round2(acuteLoad),
      chronicLoad: round2(chronicLoad),
      loadRatio: ratioBlocked ? null : round2(acuteLoad / chronicLoad),
      sessionCount: ofUnit.length,
    };
  });

  // chronic_load == 0 with no other reason is still INSUFFICIENT per REQ-LOAD-005.
  if (
    dataQuality === "OK" &&
    units.length > 0 &&
    units.every((u) => u.chronicLoad === 0)
  ) {
    dataQuality = "INSUFFICIENT";
  }

  return {
    asOfLocalDate,
    units,
    observationDays,
    missingDays,
    dataQuality,
    qualityReasons,
    daily,
    algorithmVersion: ALGORITHM_VERSION,
    schemaVersion: SCHEMA_VERSION,
  };
}

/** REQ-LOAD-008: an edit on day D only invalidates D .. D+27, not D..today. */
export function recomputeWindowFor(changedLocalDate: string): {
  fromLocalDate: string;
  toLocalDate: string;
  dayCount: number;
} {
  return {
    fromLocalDate: changedLocalDate,
    toLocalDate: shiftLocalDate(changedLocalDate, CHRONIC_WINDOW_DAYS - 1),
    dayCount: CHRONIC_WINDOW_DAYS,
  };
}

export interface TrendPoint {
  localDate: string;
  acuteLoad: number;
  chronicLoad: number;
  loadRatio: number | null;
}

/** Rolling acute/chronic for each of the last `days` days, within one unit.
 *  Needs activity history from before the plotted range — that is the point of
 *  a rolling window, and truncating it would understate the early days. */
export function rollingLoadSeries(
  activities: Activity[],
  unit: LoadUnit,
  endLocalDate: string,
  days: number,
): TrendPoint[] {
  const ofUnit = activities.filter((a) => a.unit === unit && countsTowardLoad(a));

  const loadByDate = new Map<string, number>();
  for (const a of ofUnit) {
    loadByDate.set(
      a.localTrainingDate,
      (loadByDate.get(a.localTrainingDate) ?? 0) + a.sessionLoad,
    );
  }

  const sumWindow = (endDate: string, windowDays: number): number => {
    let total = 0;
    for (let i = 0; i < windowDays; i++) {
      total += loadByDate.get(shiftLocalDate(endDate, -i)) ?? 0;
    }
    return total;
  };

  return localDateRange(endLocalDate, days).map((localDate) => {
    const acuteLoad = sumWindow(localDate, ACUTE_WINDOW_DAYS);
    const chronicLoad = sumWindow(localDate, CHRONIC_WINDOW_DAYS) / 4;
    return {
      localDate,
      acuteLoad: round2(acuteLoad),
      chronicLoad: round2(chronicLoad),
      loadRatio: chronicLoad > 0 ? round2(acuteLoad / chronicLoad) : null,
    };
  });
}

/* ---- REQ-LOAD-007: canonicalization, then SHA-256 ---- */

/** Canonical JSON: keys sorted A→Z, UTF-8, UTC ISO 8601 timestamps, and a
 *  fixed decimal precision per unit (AU is 2dp). Same inputs -> same string
 *  on any machine, which is the whole point of the hash. */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries
    .map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`)
    .join(",")}}`;
}

export function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

export function buildLoadInputSnapshot(result: TrainingLoadResult) {
  return {
    algorithm_version: result.algorithmVersion,
    as_of_local_date: result.asOfLocalDate,
    daily: result.daily.map((d) => ({
      local_date: d.localDate,
      load_by_unit: Object.fromEntries(
        Object.entries(d.loadByUnit)
          .map(([unit, load]) => [unit, round2(load as number)])
          .sort(([a], [b]) => (a < b ? -1 : 1)),
      ),
      rest_confirmed: d.restConfirmed,
    })),
    observation_days: result.observationDays,
    schema_version: result.schemaVersion,
  };
}

export async function computeInputSnapshotHash(
  result: TrainingLoadResult,
): Promise<string> {
  const canonical = canonicalJson(buildLoadInputSnapshot(result));
  const bytes = new TextEncoder().encode(canonical);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

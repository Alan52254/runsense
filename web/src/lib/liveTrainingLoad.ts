/* Adapts the real GET /training-load/trend response into the same shapes
 * TrainingLoadScreen/DashboardScreen already consume from computeTrainingLoad
 * (lib/trainingLoad.ts). This is a mapping layer only — it never recomputes
 * acute_load/chronic_load/load_ratio/data_quality, all of which come
 * straight from the server (REQ-LOAD-007/008: the server's numbers are
 * canonical; a client re-derivation would defeat the point of the hash).
 */

import type {
  TrainingLoadPointWire,
  TrainingLoadSeriesWire,
  TrainingLoadTrendWireResponse,
} from "../data/apiClient.ts";
import type { DataQuality, LoadUnit } from "./types.ts";
import type { DailyLoadPoint, TrainingLoadResult, TrendPoint, UnitLoad } from "./trainingLoad.ts";
import { round2 } from "./trainingLoad.ts";

const QUALITY_MAP: Record<TrainingLoadPointWire["data_quality"], DataQuality> = {
  SUFFICIENT: "OK",
  LOW: "LOW",
  INSUFFICIENT: "INSUFFICIENT",
};

function qualityReasonsFor(
  quality: DataQuality,
  observationDays: number,
  unitCount: number,
): string[] {
  const reasons: string[] = [];
  if (quality === "INSUFFICIENT") {
    reasons.push(`28 天內只有 ${observationDays} 天有紀錄，未達 21 天門檻`);
  } else if (quality === "LOW" && unitCount > 1) {
    reasons.push("這段期間同時有手動輸入與裝置負荷兩種單位，兩者不可相加，改為分開呈現");
  }
  return reasons;
}

export function adaptTrainingLoadSummary(
  trend: TrainingLoadTrendWireResponse,
): TrainingLoadResult {
  const dailyMap = new Map<string, DailyLoadPoint>();
  for (const series of trend.series) {
    for (const point of series.points) {
      const existing = dailyMap.get(point.date);
      const loadByUnit = existing?.loadByUnit ?? {};
      if (point.session_load > 0) {
        loadByUnit[series.unit as LoadUnit] = point.session_load;
      }
      dailyMap.set(point.date, {
        localDate: point.date,
        loadByUnit,
        hasActivity: existing?.hasActivity || point.session_load > 0,
      });
    }
  }
  const daily = [...dailyMap.values()].sort((a, b) => (a.localDate < b.localDate ? -1 : 1));

  const units: UnitLoad[] = trend.series.map((series) => {
    const last = series.points[series.points.length - 1];
    // Proxy, not a recount from raw activities: days in-window where this
    // unit had any load. Undercounts a rare multi-session day by one — the
    // footer text ("N 次訓練納入") is a nicety, not a load-bearing number.
    const sessionCount = series.points.filter((p) => p.session_load > 0).length;
    return {
      unit: series.unit as LoadUnit,
      acuteLoad: round2(last.acute_load),
      chronicLoad: round2(last.chronic_load),
      loadRatio: last.load_ratio === null ? null : round2(last.load_ratio),
      sessionCount,
    };
  });

  const primary = pickPrimary(trend.series);
  const dataQuality = primary ? QUALITY_MAP[primary.data_quality] : "INSUFFICIENT";
  const observationDays = primary?.observation_days ?? 0;

  return {
    asOfLocalDate: trend.end_date,
    units,
    observationDays,
    missingDays: 28 - observationDays,
    dataQuality,
    qualityReasons: qualityReasonsFor(dataQuality, observationDays, trend.series.length),
    daily,
    algorithmVersion: primary?.algorithm_version ?? "—",
    schemaVersion: primary ? String(primary.schema_version) : "—",
    serverInputSnapshotHash: primary?.input_snapshot_hash,
  };
}

export function trendPointsForUnit(
  trend: TrainingLoadTrendWireResponse,
  unit: LoadUnit,
): TrendPoint[] {
  const series = trend.series.find((s) => s.unit === unit);
  if (!series) return [];
  return series.points.map((p) => ({
    localDate: p.date,
    acuteLoad: round2(p.acute_load),
    chronicLoad: round2(p.chronic_load),
    loadRatio: p.load_ratio === null ? null : round2(p.load_ratio),
  }));
}

/** AU first when present (matches the backend's own ORDER BY), else
 *  whatever the single series is. Mirrors DashboardScreen's existing
 *  `units[0]` "primary unit" convention. */
function pickPrimary(series: TrainingLoadSeriesWire[]): TrainingLoadPointWire | null {
  const au = series.find((s) => s.unit === "AU");
  const chosen = au ?? series[0];
  if (!chosen || chosen.points.length === 0) return null;
  return chosen.points[chosen.points.length - 1];
}

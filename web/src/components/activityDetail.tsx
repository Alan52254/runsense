/* Shared "what actually happened" detail panel for one Activity -- stats
 * grid, workout structure, and lap splits. Used by the athlete's own
 * History screen and the coach's Athlete Detail screen alike (the coach
 * view is read-only from a different data source -- a per-date fetch
 * rather than the athlete's own paginated history -- but the rendering is
 * identical once an Activity is in hand). */

import { useMemo, useState } from "react";
import { Card } from "./ui.tsx";
import { WorkoutStructureView, assignmentSegmentToDisplay } from "./workoutStructure.tsx";
import { generateActivityLaps, type LapKind } from "../lib/lapSynthesis.ts";
import { formatPace } from "../lib/format.ts";
import type { Activity } from "../lib/types.ts";

const LAP_KIND_LABEL: Record<LapKind, { "zh-TW": string; en: string }> = {
  warmup: { "zh-TW": "熱身", en: "Warm-up" },
  work: { "zh-TW": "強度", en: "Work" },
  rest: { "zh-TW": "休息", en: "Rest" },
  cooldown: { "zh-TW": "收操", en: "Cool-down" },
  steady: { "zh-TW": "跑步", en: "Run" },
};

function formatClockFromSeconds(totalSec: number): string {
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** heart rate / pace / cadence / elevation / calories / training effect /
 *  structure, whatever a row happens to have -- distance+RPE-only manual
 *  entries will have none of this, device-imported history usually has
 *  most of it. */
export function ActivityDetailPanel({ activity, locale }: { activity: Activity; locale: "zh-TW" | "en" }) {
  const en = locale === "en";
  const [expandedSegmentKey, setExpandedSegmentKey] = useState<string | null>(null);
  const laps = useMemo(() => generateActivityLaps(activity), [activity]);
  const m = activity.deviceMetrics;
  const paceSecPerKm =
    activity.distanceKm && activity.distanceKm > 0
      ? (activity.durationMinutes * 60) / activity.distanceKm
      : null;

  const stats: { label: string; value: string }[] = [];
  if (activity.distanceKm) stats.push({ label: en ? "Distance" : "距離", value: `${activity.distanceKm} km` });
  if (paceSecPerKm !== null) stats.push({ label: en ? "Avg pace" : "平均配速", value: formatPace(paceSecPerKm) });
  if (m.avgHeartRate !== undefined)
    stats.push({
      label: en ? "Heart rate" : "心率",
      value: m.maxHeartRate !== undefined ? `${m.avgHeartRate} / ${m.maxHeartRate} bpm` : `${m.avgHeartRate} bpm`,
    });
  if (m.avgCadenceStepsPerMin !== undefined)
    stats.push({ label: en ? "Cadence" : "步頻", value: `${m.avgCadenceStepsPerMin} spm` });
  if (m.avgStrideLengthM !== undefined)
    stats.push({ label: en ? "Stride length" : "步幅", value: `${m.avgStrideLengthM} m` });
  if (m.elevationGainM !== undefined || m.elevationLossM !== undefined)
    stats.push({
      label: en ? "Elevation" : "海拔爬升／下降",
      value: `${en ? "+" : "↑"}${m.elevationGainM ?? 0} / ${en ? "-" : "↓"}${m.elevationLossM ?? 0} m`,
    });
  if (m.calories !== undefined) stats.push({ label: en ? "Calories" : "熱量", value: `${m.calories} kcal` });
  if (m.aerobicTrainingEffect !== undefined)
    stats.push({
      label: en ? "Training effect" : "訓練效果",
      value: `${m.aerobicTrainingEffect}${m.anaerobicTrainingEffect ? ` / ${m.anaerobicTrainingEffect}` : ""}${m.trainingEffectLabel ? ` (${m.trainingEffectLabel})` : ""}`,
    });

  const hasStructure = activity.structure.length > 0;

  if (stats.length === 0 && !hasStructure && laps.length === 0) {
    return (
      <div className="field-hint" style={{ padding: "12px 4px" }}>
        {en ? "No further detail for this record." : "這筆紀錄沒有更多詳細資料。"}
      </div>
    );
  }

  return (
    <div className="stack-sm" style={{ padding: "12px 4px" }}>
      {stats.length > 0 && (
        <div className="grid-4" style={{ gap: 10 }}>
          {stats.map((s) => (
            <div key={s.label}>
              <div className="field-hint" style={{ fontSize: 11 }}>{s.label}</div>
              <div className="tnum" style={{ fontSize: 14, fontWeight: 600 }}>{s.value}</div>
            </div>
          ))}
        </div>
      )}
      {hasStructure && (
        <WorkoutStructureView
          segments={activity.structure.map((segment, index) => assignmentSegmentToDisplay(segment, index, locale))}
          heading={en ? "Workout structure" : "課表結構"}
          expandedKey={expandedSegmentKey}
          onToggleExpand={(key) => setExpandedSegmentKey((current) => (current === key ? null : key))}
        />
      )}
      {laps.length > 0 && (
        <Card title={en ? "Lap splits" : "分圈紀錄"} flush>
          <div className="table-scroll">
            <table className="splits-table">
              <thead>
                <tr>
                  <th>{en ? "Lap" : "圈數"}</th>
                  <th>{en ? "Distance" : "距離"}</th>
                  <th>{en ? "Pace" : "配速"}</th>
                  <th>{en ? "Time" : "時間"}</th>
                  <th>{en ? "Avg HR" : "平均心率"}</th>
                  <th>{en ? "Max HR" : "最高心率"}</th>
                </tr>
              </thead>
              <tbody>
                {laps.map((lap) => (
                  <tr key={lap.lapNumber}>
                    <td>
                      <strong>{lap.lapNumber}</strong>{" "}
                      <span className="field-hint">{LAP_KIND_LABEL[lap.kind][locale]}</span>
                    </td>
                    <td>{lap.distanceKm} km</td>
                    <td>{formatPace(lap.avgPaceSecPerKm)}</td>
                    <td>{formatClockFromSeconds(lap.durationSec)}</td>
                    <td>{lap.avgHrBpm !== null ? `${lap.avgHrBpm} bpm` : "—"}</td>
                    <td>{lap.maxHrBpm !== null ? `${lap.maxHrBpm} bpm` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

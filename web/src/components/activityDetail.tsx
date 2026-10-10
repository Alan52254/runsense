/* Shared "what actually happened" detail panel for one Activity -- stats
 * grid, workout structure, and lap splits. Used by the athlete's own
 * History screen and the coach's Athlete Detail screen alike (the coach
 * view is read-only from a different data source -- a per-date fetch
 * rather than the athlete's own paginated history -- but the rendering is
 * identical once an Activity is in hand). */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card } from "./ui.tsx";
import { RealLapTable, WorkoutAnalysisModal } from "./workoutAnalysis.tsx";
import { PrescriptionCard } from "./workoutPrescription.tsx";
import { ApiError, apiConfigured, getActivityTelemetry } from "../data/apiClient.ts";
import type { ActivityTelemetryWire, LinkedRecordsWire, PrescriptionWire } from "../data/apiClient.ts";
import type { WorkoutAssignmentSegment } from "../lib/types.ts";
import { useAuth } from "../state/AuthContext.tsx";
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
  const { auth } = useAuth();
  const accessToken = auth?.accessToken ?? null;
  const [expandedSegmentKey, setExpandedSegmentKey] = useState<string | null>(null);
  const laps = useMemo(() => generateActivityLaps(activity), [activity]);
  // Real per-lap data recorded by the watch (activities imported with their
  // .fit file). Everything else keeps the estimated laps below, labelled
  // as estimates.
  const [telemetry, setTelemetry] = useState<ActivityTelemetryWire | null>(null);
  const [telemetryState, setTelemetryState] = useState<"idle" | "loading" | "none" | "ready" | "error">("idle");
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const canFetchTelemetry = apiConfigured && !!accessToken && activity.provider === "garmin" && activity.syncState === "SYNCED";

  const loadTelemetry = useCallback(async () => {
    if (!canFetchTelemetry || !accessToken) return;
    setTelemetryState("loading");
    try {
      setTelemetry(await getActivityTelemetry(accessToken, activity.id));
      setTelemetryState("ready");
    } catch (e) {
      // 404: no recorded file for this activity, or it is another athlete's
      // (the coach view) -- both fall back to the estimate
      setTelemetryState(e instanceof ApiError && e.status === 404 ? "none" : "error");
    }
  }, [canFetchTelemetry, accessToken, activity.id]);

  useEffect(() => {
    void loadTelemetry();
  }, [loadTelemetry]);
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

  // with a prescription, the structure shows what was prescribed -- each
  // rep's pace -- framed by the warm-up / cool-down (this record's own, or
  // the separate records just before / after it)
  const structure = telemetry?.coach_easy_day
    ? [{ kind: "jog" as const, label: telemetry.coach_easy_day, distanceMeters: activity.distanceKm ? Math.round(activity.distanceKm * 1000) : undefined,
         durationSeconds: Math.round(activity.durationMinutes * 60) }]
    : telemetry?.prescription
      ? structureFromPrescription(telemetry.prescription, activity.structure, telemetry.linked)
      : activity.structure.filter((seg) => !isNoiseSegment(seg));
  const hasStructure = structure.length > 0;

  if (stats.length === 0 && !hasStructure && laps.length === 0 && !telemetry) {
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
          segments={structure.map((segment, index) => assignmentSegmentToDisplay(segment, index, locale))}
          heading={en ? "Workout structure" : "課表結構"}
          expandedKey={expandedSegmentKey}
          onToggleExpand={(key) => setExpandedSegmentKey((current) => (current === key ? null : key))}
        />
      )}
      {telemetry && accessToken && (telemetry.prescription || telemetry.detection.kind !== "continuous") && (
        <PrescriptionCard
          activityId={activity.id}
          accessToken={accessToken}
          prescription={telemetry.prescription}
          activityName={telemetry.activity_name}
          onChanged={() => void loadTelemetry()}
          control
        />
      )}
      {telemetry && (
        <div className="analysis-entry">
          <div>
            <strong>{en ? "AI workout analysis" : "AI 課表分析"}</strong>
            <div className="field-hint">
              {en
                ? "Reads which laps were reps and which were recoveries, then analyses pacing, heart rate and recovery like a coach."
                : "判讀哪幾圈是課表、哪幾圈是組間休息，再像教練一樣分析配速控制、心率與恢復。"}
            </div>
          </div>
          <Button variant="primary" icon="activity" onClick={() => setAnalysisOpen(true)}>
            {telemetry.has_analysis ? (en ? "View analysis" : "查看分析") : (en ? "AI analysis" : "AI 分析")}
          </Button>
        </div>
      )}
      {telemetry && <RealLapTable telemetry={telemetry} locale={locale} />}
      {telemetry && accessToken && (
        <WorkoutAnalysisModal
          open={analysisOpen}
          onClose={() => setAnalysisOpen(false)}
          activityId={activity.id}
          accessToken={accessToken}
          locale={locale}
          onAnalysed={() => void loadTelemetry()}
        />
      )}
      {telemetryState === "loading" && (
        <div className="field-hint" style={{ padding: "6px 2px" }}>{en ? "Loading recorded laps…" : "讀取手錶實測分圈…"}</div>
      )}
      {!telemetry && telemetryState !== "loading" && laps.length > 0 && (
        <Card
          title={en ? "Lap splits (estimated)" : "分圈紀錄（推估，非實測）"}
          subtitle={en
            ? "This record has no per-lap file from a watch; splits are reconstructed from the workout structure."
            : "這筆紀錄沒有手錶的逐圈檔案，以下分圈依課表結構推估，僅供參考。"}
          flush
        >
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

function isNoiseSegment(seg: WorkoutAssignmentSegment): boolean {
  // a few metres / seconds of "cool-down" after the last rep is the watch
  // being stopped, not a cool-down
  return (seg.kind === "warmup" || seg.kind === "cooldown") && (seg.durationSeconds ?? 0) < 180;
}

function paceLabel(distance: number | null, pace: number): string {
  if (distance && distance <= 600) return `${Math.round((pace * distance) / 1000)} 秒`;
  const t = Math.round(pace);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")} /km`;
}

function structureFromPrescription(
  p: PrescriptionWire,
  recorded: WorkoutAssignmentSegment[],
  linked: LinkedRecordsWire,
): WorkoutAssignmentSegment[] {
  const out: WorkoutAssignmentSegment[] = [];
  const warm = recorded.find((seg) => seg.kind === "warmup" && !isNoiseSegment(seg));
  const cool = recorded.find((seg) => seg.kind === "cooldown" && !isNoiseSegment(seg));
  if (linked.warmup) {
    out.push({ kind: "warmup", label: `熱身（${linked.warmup.start_local} 另一筆）`,
      distanceMeters: Math.round(linked.warmup.distance_km * 1000), durationSeconds: linked.warmup.duration_s });
  } else if (warm) out.push(warm);

  // consecutive single-rep blocks (2000-1000-800) read as one ladder
  let i = 0;
  const blocks = p.blocks;
  while (i < blocks.length) {
    const b = blocks[i];
    const group = [b];
    if (b.reps === 1) {
      while (i + group.length < blocks.length && blocks[i + group.length].reps === 1) group.push(blocks[i + group.length]);
    }
    const distances: number[] = [];
    const paces: string[] = [];
    for (const g of group) {
      for (let k = 0; k < g.reps; k++) {
        if (g.distance_m) distances.push(g.distance_m);
        const t = g.targets_s_per_km.length === g.reps ? g.targets_s_per_km[k] : g.targets_s_per_km[0];
        paces.push(t !== undefined ? paceLabel(g.distance_m, t) : "—");
      }
    }
    const uniquePaces = [...new Set(paces)];
    const sameDistance = distances.length > 0 && new Set(distances).size === 1;
    out.push({
      kind: "interval",
      label: "間歇",
      repetitions: distances.length || group.reduce((n, g) => n + g.reps, 0),
      // "× 10 · 400m" rather than listing 400m ten times; per-rep
      // distances only when they differ or each rep has its own pace
      distanceMeters: sameDistance && uniquePaces.length === 1 ? distances[0] : undefined,
      distancesMeters: distances.length && !(sameDistance && uniquePaces.length === 1) ? distances : undefined,
      durationSeconds: !distances.length ? group[0].duration_s ?? undefined : undefined,
      pace: uniquePaces.length === 1 ? uniquePaces[0] : uniquePaces.join(" → "),
      pacesPerRep: uniquePaces.length > 1 ? paces : undefined,
      restSeconds: group[0].rest_s ?? group[group.length - 1].rest_after_s ?? undefined,
    });
    const after = group[group.length - 1].rest_after_s;
    if (i + group.length < blocks.length && after && after !== group[0].rest_s) {
      out.push({ kind: "rest", label: "組間休息", durationSeconds: after });
    }
    i += group.length;
  }

  if (linked.cooldown) {
    out.push({ kind: "cooldown", label: `收操（${linked.cooldown.start_local} 另一筆）`,
      distanceMeters: Math.round(linked.cooldown.distance_km * 1000), durationSeconds: linked.cooldown.duration_s });
  } else if (cool) out.push(cool);
  return out;
}

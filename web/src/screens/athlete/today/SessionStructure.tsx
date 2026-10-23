import { useEffect, useState } from "react";
import { GlassPanel, Rail } from "../../../components/motion.tsx";
import type { RailStage } from "../../../components/motion.tsx";
import type { IconName } from "../../../components/Icon.tsx";
import type { DisplaySegment } from "../../../components/workoutStructure.tsx";
import { assignmentSegmentToDisplay, recommendationSegmentToDisplay } from "../../../components/workoutStructure.tsx";
import { applyWeatherToSegmentPace, computeSegmentStartOffsetsMinutes } from "../../../lib/paceCalc.ts";
import { resolveTimeOfDaySlot } from "../../../lib/todayViewModel.ts";
import type { AssignedWorkout, TimeOfDayTemperatureEstimate, WorkoutAssignmentSegment, WorkoutSegment } from "../../../lib/types.ts";
import { apiConfigured, getWeather } from "../../../data/apiClient.ts";
import { interpolate, type TodayCopy } from "./todayCopy.ts";
import { paceShiftText } from "../../../lib/climateShift.ts";
import { Row, Stack } from "../../../components/Layout.tsx";
import { Text } from "../../../components/Text.tsx";

type Locale = "zh-TW" | "en";

function kindIcon(kind: string): IconName {
  if (kind === "warmup" || kind === "cooldown" || kind === "jog") return "runner";
  if (kind === "recovery" || kind === "rest") return "moon";
  return "energy";
}

function toRailStages(segments: DisplaySegment[]): RailStage[] {
  return segments.map((segment) => ({
    id: segment.key,
    icon: kindIcon(segment.kind),
    title: (
      <>
        {segment.label}
        {segment.repetitions ? <span className="ath-reps"> × {segment.repetitions}</span> : null}
      </>
    ),
    meta: segment.detail ?? undefined,
    detail: [segment.weatherNote, segment.afterNote].filter(Boolean).join(" · ") || undefined,
  }));
}

/** "now + offsetMinutes" as a local "HH:MM", purely as a label. */
function formatOffsetClockTime(offsetMinutes: number): string {
  const at = new Date(Date.now() + offsetMinutes * 60_000);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

/** The detail under a coach-assigned block: this block's weather-adjusted
 *  pace at its own estimated start time, not one "now" figure for the whole
 *  workout. `pct` is null while the estimate is still loading. */
function SegmentWeatherDetail({ segment, offsetMinutes, pct, c, locale }: {
  locale: "zh-TW" | "en";
  segment: WorkoutAssignmentSegment;
  offsetMinutes: number;
  pct: number | null;
  c: TodayCopy;
}) {
  if (pct === null) return <Text variant="caption">{c.segmentWeatherLoading}</Text>;
  const adjusted = applyWeatherToSegmentPace(segment, pct);
  return (
    <Stack gap={2} className="ath-seg-weather">
      <Row justify="between">
        <span className="muted">{interpolate(c.segmentEstimatedTime, { time: formatOffsetClockTime(offsetMinutes) })}</span>
        <strong className="ath-seg-weather__loss">{locale === "en" ? `Pace ${paceShiftText(pct, locale)}` : `配速${paceShiftText(pct, locale)}`}</strong>
      </Row>
      {adjusted.pace && adjusted.pace !== segment.pace ? (
        <span>{interpolate(c.segmentPaceAdjusted, { from: segment.pace ?? "", to: adjusted.pace })}</span>
      ) : (
        <Text variant="caption">{c.segmentPaceUnchanged}</Text>
      )}
    </Stack>
  );
}

/** One coach assignment's block rail. Click a block for its weather detail:
 *  the live API is asked for each block's start time; the offline demo uses
 *  the nearest of the three fixed time-of-day slots. */
export function CoachSessionStructure({ assignment, accessToken, coachPaceLossPct, slots, c, locale }: {
  assignment: AssignedWorkout;
  accessToken: string | null;
  coachPaceLossPct: number;
  slots: TimeOfDayTemperatureEstimate[];
  c: TodayCopy;
  locale: Locale;
}) {
  const en = locale === "en";
  const structure = assignment.structure ?? [];
  const offsets = computeSegmentStartOffsetsMinutes(structure);
  const [estimates, setEstimates] = useState<number[] | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const offsetsKey = offsets.join(",");

  useEffect(() => {
    if (!apiConfigured || !accessToken || offsets.length === 0) return;
    getWeather(accessToken, offsets)
      .then((res) => setEstimates(res.segment_estimates.map((e) => e.speed_loss_pct)))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, offsetsKey]);

  function pctAt(offsetMinutes: number, index: number): number | null {
    if (apiConfigured) return estimates?.[index] ?? null;
    const hour = (new Date().getHours() + offsetMinutes / 60) % 24;
    return resolveTimeOfDaySlot(slots, hour)?.speedLossPct ?? coachPaceLossPct;
  }

  const display = structure.map((segment, i) =>
    assignmentSegmentToDisplay(applyWeatherToSegmentPace(segment, coachPaceLossPct), i, locale),
  );
  if (display.length === 0) return null;
  const openIndex = openKey ? display.findIndex((d) => d.key === openKey) : -1;
  const title = en ? "Session structure" : "訓練結構";

  return (
    <GlassPanel className="ath-panel" as="section" aria-label={title}>
      <h2 className="ath-panel-title">{title}</h2>
      <Rail label={title} stages={toRailStages(display)} onSelect={(key) => setOpenKey((prev) => (prev === key ? null : key))} />
      {openIndex >= 0 && structure[openIndex] && (
        <div className="ath-rail-note">
          <SegmentWeatherDetail
            locale={locale}
            segment={structure[openIndex]!}
            offsetMinutes={offsets[openIndex] ?? 0}
            pct={pctAt(offsets[openIndex] ?? 0, openIndex)}
            c={c}
          />
        </div>
      )}
      {coachPaceLossPct !== 0 && (
        <p className="ath-rail-note">{interpolate(c.coachPaceWeatherNote, { shift: paceShiftText(coachPaceLossPct, locale) })}</p>
      )}
    </GlassPanel>
  );
}

export function SystemSessionStructure({ segments, speedLossPct, locale }: {
  segments: WorkoutSegment[];
  speedLossPct: number;
  locale: Locale;
}) {
  const en = locale === "en";
  if (segments.length === 0) return null;
  const display = segments.map((segment) => recommendationSegmentToDisplay(segment, speedLossPct, locale));
  const title = en ? "Session structure" : "訓練結構";
  return (
    <GlassPanel className="ath-panel" as="section" aria-label={title}>
      <h2 className="ath-panel-title">{title}</h2>
      <p className="ath-panel-sub">{en ? "Work and recovery are separated" : "工作段與恢復段分開計算"}</p>
      <Rail label={title} stages={toRailStages(display)} />
    </GlassPanel>
  );
}

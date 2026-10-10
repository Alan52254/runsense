/* Renders a workout's block-by-block structure as the same rich segment-card
 * grid everywhere it appears: the athlete's auto-generated plan (recommendation
 * segments) and a coach-assigned workout (assignment segments) are two
 * different shapes on the wire, so each gets its own adapter into the one
 * DisplaySegment the card actually renders. */

import type { ReactNode } from "react";
import type { WorkoutAssignmentSegment } from "../lib/types.ts";
import { formatPace } from "../lib/format.ts";
import { applyPctToPace } from "../lib/paceCalc.ts";

/** Structurally compatible with WorkoutSegment, but also with the looser
 *  `kind: string` shape the live guidance wire response carries — the two
 *  branches DashboardScreen ternaries between (demo vs. live) don't share an
 *  exact type, only this shape. */
interface RecommendationSegmentLike {
  id: string;
  kind: string;
  label: string;
  distanceMeters?: number;
  durationSeconds?: number;
  repetitions?: number;
  targetPaceSecPerKm?: number | null;
  targetPaceRangeSecPerKm?: readonly [number, number] | number[] | null;
  afterRepetition?: string;
}

export interface DisplaySegment {
  key: string;
  kind: string;
  label: string;
  repetitions?: number;
  detail?: string;
  afterNote?: string;
  /** This segment's own weather-equivalent pace (see DashboardScreen.tsx's
   *  speedLossPct), shown alongside -- not replacing -- the prescribed
   *  pace in `detail`, so both the plan and today's real-condition
   *  adjustment stay visible at once. Distinct from afterNote so the two
   *  never collide on a segment that has both a rep-rest note and a
   *  weather adjustment. */
  weatherNote?: string;
  /** Rendered inline below the card when this segment is the expanded one
   *  (see WorkoutStructureView's `expandedKey`/`onToggleExpand`). Only
   *  present when the caller wants this specific card to be clickable --
   *  omit it to keep a card static, as every card is by default. */
  expandedContent?: ReactNode;
}

function formatMetersOrKm(distanceMeters?: number): string | null {
  if (!distanceMeters) return null;
  return distanceMeters >= 1000
    ? `${Number((distanceMeters / 1000).toFixed(2)).toString()} km`
    : `${distanceMeters} m`;
}

function formatClock(durationSeconds?: number): string | null {
  if (!durationSeconds) return null;
  const mins = Math.floor(durationSeconds / 60);
  const secs = Math.round(durationSeconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function formatRestNote(restSeconds: number | undefined, locale: "zh-TW" | "en"): string | undefined {
  if (!restSeconds) return undefined;
  const clock = restSeconds < 60 ? `${restSeconds}s` : formatClock(restSeconds);
  return locale === "en" ? `Rest ${clock} between reps` : `每趟間休息 ${clock}`;
}

function perRepBreakdown(
  distancesMeters: number[],
  pacesPerRep: string[],
  locale: "zh-TW" | "en",
): ReactNode {
  return (
    <div className="stack-sm" style={{ fontSize: 11.5 }}>
      {distancesMeters.map((meters, i) => (
        <div className="row-between" key={i}>
          <span className="muted">{locale === "en" ? `Rep ${i + 1}` : `第 ${i + 1} 趟`}</span>
          <span className="tnum">
            {formatMetersOrKm(meters)} · {pacesPerRep[i] ?? "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

export function recommendationSegmentToDisplay(
  segment: RecommendationSegmentLike,
  speedLossPct = 0,
  locale: "zh-TW" | "en" = "zh-TW",
): DisplaySegment {
  const distance = formatMetersOrKm(segment.distanceMeters);
  const duration = formatClock(segment.durationSeconds);
  const pace = segment.targetPaceRangeSecPerKm
    ? `${formatPace(segment.targetPaceRangeSecPerKm[0])}–${formatPace(segment.targetPaceRangeSecPerKm[1])}`
    : segment.targetPaceSecPerKm
      ? formatPace(segment.targetPaceSecPerKm)
      : null;

  // Today's real-condition equivalent of this segment's own prescribed
  // pace -- kept as a separate note (not folded into `detail`) so the
  // plan's own pace and today's weather adjustment both stay legible,
  // matching how the coach-assigned segment cards already surface this
  // via segmentWeatherDetail in DashboardScreen.tsx.
  let weatherNote: string | undefined;
  if (speedLossPct > 0) {
    const weatherLabel = locale === "en" ? "Weather-equiv." : "天候等效";
    if (segment.targetPaceRangeSecPerKm) {
      const [lo, hi] = segment.targetPaceRangeSecPerKm;
      weatherNote = `${weatherLabel} ${formatPace(applyPctToPace(lo, speedLossPct))}–${formatPace(applyPctToPace(hi, speedLossPct))}`;
    } else if (segment.targetPaceSecPerKm) {
      weatherNote = `${weatherLabel} ${formatPace(applyPctToPace(segment.targetPaceSecPerKm, speedLossPct))}`;
    }
  }

  return {
    key: segment.id,
    kind: segment.kind,
    label: segment.label,
    repetitions: segment.repetitions,
    detail: [distance, duration, pace].filter(Boolean).join(" · ") || undefined,
    afterNote: segment.afterRepetition ? `每趟後 ${segment.afterRepetition}` : undefined,
    weatherNote,
  };
}

/** "3:15 /km 以內（每趟 78 秒內）": the pace as prescribed -- an upper limit
 *  is marked as one, and repeated reps also get the per-rep time. */
function prescribedPace(segment: WorkoutAssignmentSegment, locale: "zh-TW" | "en"): string | undefined {
  if (!segment.pace) return undefined;
  const en = locale === "en";
  const max = segment.paceMode === "max";
  let text = max ? `${segment.pace} ${en ? "or faster" : "以內"}` : segment.pace;
  const m = /(\d+):(\d{2}(?:\.\d)?)/.exec(segment.pace);
  if (m && segment.distanceMeters && (segment.repetitions ?? 1) > 1) {
    const perRep = Math.round(((Number(m[1]) * 60 + Number(m[2])) * segment.distanceMeters) / 1000 * 10) / 10;
    const per = perRep < 120 ? `${perRep}${en ? " s" : " 秒"}` : `${Math.floor(perRep / 60)}:${String(Math.round(perRep % 60)).padStart(2, "0")}`;
    text += en ? ` (${per} per rep${max ? " or less" : ""})` : `（每趟 ${per}${max ? "內" : ""}）`;
  }
  return text;
}

export function assignmentSegmentToDisplay(
  segment: WorkoutAssignmentSegment,
  index: number,
  locale: "zh-TW" | "en",
  expandedContent?: ReactNode,
): DisplaySegment {
  const hasCustomReps = (segment.distancesMeters?.length ?? 0) > 0;
  const distance = hasCustomReps
    ? segment.distancesMeters!.map((m) => (m >= 1000 ? `${m / 1000}km` : `${m}m`)).join(" / ")
    : formatMetersOrKm(segment.distanceMeters);
  const duration = formatClock(segment.durationSeconds);
  const hasPerRepPaces = (segment.pacesPerRep?.length ?? 0) > 0 && hasCustomReps;
  return {
    key: `${index}-${segment.kind}`,
    kind: segment.kind,
    label: segment.label,
    repetitions: hasCustomReps ? segment.distancesMeters!.length : segment.repetitions,
    detail: [distance, duration, prescribedPace(segment, locale)].filter(Boolean).join(" · ") || undefined,
    afterNote: formatRestNote(segment.restSeconds, locale),
    expandedContent:
      expandedContent ??
      (hasPerRepPaces ? perRepBreakdown(segment.distancesMeters!, segment.pacesPerRep!, locale) : undefined),
  };
}

export function WorkoutStructureView({
  segments,
  heading,
  subheading,
  expandedKey,
  onToggleExpand,
}: {
  segments: DisplaySegment[];
  heading: string;
  subheading?: string;
  /** Key of the currently-expanded segment, if any -- only meaningful for
   *  cards that carry `expandedContent`. */
  expandedKey?: string | null;
  onToggleExpand?: (key: string) => void;
}) {
  if (segments.length === 0) return null;
  return (
    <div className="workout-structure" aria-label={heading}>
      <div className="workout-structure-head">
        <span>{heading}</span>
        {subheading && <span className="field-hint">{subheading}</span>}
      </div>
      <div className="workout-segments">
        {segments.map((segment, index) => {
          const clickable = segment.expandedContent !== undefined && onToggleExpand !== undefined;
          const expanded = clickable && expandedKey === segment.key;
          return (
            <div
              className={`workout-segment workout-segment-${segment.kind}${clickable ? " workout-segment-clickable" : ""}`}
              key={segment.key}
              onClick={clickable ? () => onToggleExpand!(segment.key) : undefined}
              role={clickable ? "button" : undefined}
              tabIndex={clickable ? 0 : undefined}
            >
              <span className="workout-segment-index">{String(index + 1).padStart(2, "0")}</span>
              <div className="workout-segment-main">
                <strong>{segment.label}</strong>
                {segment.repetitions ? <span className="workout-reps">× {segment.repetitions}</span> : null}
                {segment.detail && <span className="workout-segment-detail">{segment.detail}</span>}
                {segment.weatherNote && <span className="workout-segment-weather">{segment.weatherNote}</span>}
                {segment.afterNote && <span className="workout-segment-recovery">{segment.afterNote}</span>}
                {expanded && <div className="workout-segment-expanded">{segment.expandedContent}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

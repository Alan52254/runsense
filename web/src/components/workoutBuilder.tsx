/* The coach's per-segment editor: one card per workout block, its fields
 * chosen by `segment.kind` so a coach only ever sees inputs that apply to the
 * block they're building (pace/time for a warm-up, reps/distance/rest for an
 * interval, a plain duration for a rest break, and so on). */

import { useState } from "react";
import { Button, Field, Segmented } from "./ui.tsx";
import { Icon } from "./Icon.tsx";
import type { WorkoutAssignmentSegment } from "../lib/types.ts";
import {
  estimateSegmentSeconds,
  formatSecPerKmToMMSS,
  paceSecPerKmFromDistanceAndSeconds,
  paceSecPerKmFromSegment,
  secondsFromDistanceAndPace,
} from "../lib/paceCalc.ts";

export type BuilderSegment = WorkoutAssignmentSegment & { _uid: string };

type Locale = "zh-TW" | "en";

const KIND_DEFAULT_LABEL: Record<WorkoutAssignmentSegment["kind"], { zh: string; en: string }> = {
  warmup: { zh: "熱身", en: "Warm-up" },
  interval: { zh: "間歇", en: "Interval" },
  recovery: { zh: "小休", en: "Short rest" },
  rest: { zh: "大休", en: "Rest" },
  jog: { zh: "慢跑", en: "Easy jog" },
  cooldown: { zh: "收操", en: "Cool-down" },
};

export const SEGMENT_KIND_ORDER: WorkoutAssignmentSegment["kind"][] = [
  "warmup",
  "interval",
  "recovery",
  "rest",
  "jog",
  "cooldown",
];

export const KIND_ADD_LABEL: Record<WorkoutAssignmentSegment["kind"], { zh: string; en: string }> = {
  warmup: { zh: "＋熱身", en: "+ Warm-up" },
  interval: { zh: "＋間歇", en: "+ Interval" },
  recovery: { zh: "＋小休", en: "+ Short rest" },
  rest: { zh: "＋大休", en: "+ Rest" },
  jog: { zh: "＋慢跑", en: "+ Easy jog" },
  cooldown: { zh: "＋收操", en: "+ Cool-down" },
};

export function newBuilderSegment(kind: WorkoutAssignmentSegment["kind"], locale: Locale): BuilderSegment {
  const label = locale === "en" ? KIND_DEFAULT_LABEL[kind].en : KIND_DEFAULT_LABEL[kind].zh;
  const base = { _uid: crypto.randomUUID(), kind, label };
  switch (kind) {
    case "warmup":
    case "cooldown":
      return { ...base, distanceMeters: 1000, durationSeconds: 600 };
    case "jog":
      return { ...base, durationSeconds: 600 };
    case "interval":
      return { ...base, distanceMeters: 400, repetitions: 6, restSeconds: 90 };
    case "recovery":
      return { ...base, durationSeconds: 60 };
    case "rest":
      return { ...base, durationSeconds: 180 };
  }
}

function parsePaceParts(pace?: string): { min: string; max: string } {
  if (!pace) return { min: "", max: "" };
  const clean = pace.replace(/\s*\/\s*km$/i, "").trim();
  const [a, b] = clean.split(/[–-]/).map((part) => part.replace(/\/km/i, "").trim());
  return { min: a ?? "", max: b && b !== a ? b : "" };
}

function composePace(min: string, max: string): string | undefined {
  const a = min.trim();
  const b = max.trim();
  if (!a && !b) return undefined;
  if (a && b && a !== b) return `${a} /km–${b} /km`;
  return `${a || b} /km`;
}

function PaceRangeField({
  locale,
  min,
  max,
  onChange,
}: {
  locale: Locale;
  min: string;
  max: string;
  onChange: (min: string, max: string) => void;
}) {
  const en = locale === "en";
  return (
    <Field label={en ? "Target pace (mm:ss, optional)" : "目標配速（mm:ss，選填）"}>
      <div className="row" style={{ gap: 6 }}>
        <input
          className="input"
          style={{ maxWidth: 92 }}
          placeholder="5:30"
          value={min}
          onChange={(e) => onChange(e.target.value, max)}
        />
        <span className="field-hint">–</span>
        <input
          className="input"
          style={{ maxWidth: 92 }}
          placeholder={en ? "optional" : "選填"}
          value={max}
          onChange={(e) => onChange(min, e.target.value)}
        />
        <span className="field-hint">/km</span>
      </div>
    </Field>
  );
}

function DurationField({
  label,
  locale,
  seconds,
  onChange,
}: {
  label: string;
  locale: Locale;
  seconds: number | undefined;
  onChange: (seconds: number | undefined) => void;
}) {
  const en = locale === "en";
  const [unit, setUnit] = useState<"min" | "sec">(
    seconds !== undefined && seconds > 0 && seconds < 60 ? "sec" : "min",
  );
  const displayValue = seconds === undefined ? "" : unit === "min" ? String(seconds / 60) : String(seconds);

  return (
    <Field label={label}>
      <div className="row" style={{ gap: 6 }}>
        <input
          className="input"
          type="number"
          min={0}
          step={unit === "min" ? 0.5 : 5}
          value={displayValue}
          onChange={(e) => {
            if (e.target.value === "") {
              onChange(undefined);
              return;
            }
            const v = Number(e.target.value);
            if (!Number.isFinite(v)) return;
            onChange(Math.round(unit === "min" ? v * 60 : v));
          }}
        />
        <Segmented
          value={unit}
          onChange={setUnit}
          options={[
            { value: "min", label: en ? "min" : "分" },
            { value: "sec", label: en ? "sec" : "秒" },
          ]}
        />
      </div>
    </Field>
  );
}

export function SegmentEditorCard({
  segment,
  index,
  total,
  locale,
  onChange,
  onRemove,
  onMove,
}: {
  segment: BuilderSegment;
  index: number;
  total: number;
  locale: Locale;
  onChange: (patch: Partial<WorkoutAssignmentSegment>) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const en = locale === "en";
  const paceParts = parsePaceParts(segment.pace);
  const hasCustomReps = (segment.distancesMeters?.length ?? 0) > 0;
  const estimate = estimateSegmentSeconds(segment);

  // Distance is the anchor a coach sets from course knowledge. Editing
  // distance or pace recomputes duration; editing duration directly
  // recomputes pace instead -- never distance, and never both at once, so
  // the three fields can't fight each other while the coach is typing.
  function handleDistanceChange(distanceMeters: number | undefined) {
    const patch: Partial<WorkoutAssignmentSegment> = { distanceMeters };
    const paceSecPerKm = paceSecPerKmFromSegment(segment.pace);
    if (distanceMeters !== undefined && paceSecPerKm !== null) {
      patch.durationSeconds = Math.round(secondsFromDistanceAndPace(distanceMeters, paceSecPerKm));
    }
    onChange(patch);
  }

  function handleDurationChange(durationSeconds: number | undefined) {
    const patch: Partial<WorkoutAssignmentSegment> = { durationSeconds };
    if (durationSeconds !== undefined && segment.distanceMeters) {
      const paceSecPerKm = paceSecPerKmFromDistanceAndSeconds(segment.distanceMeters, durationSeconds);
      if (paceSecPerKm !== null) {
        const formatted = formatSecPerKmToMMSS(paceSecPerKm);
        patch.pace = composePace(formatted, formatted);
      }
    }
    onChange(patch);
  }

  function handlePaceChange(min: string, max: string) {
    const pace = composePace(min, max);
    const patch: Partial<WorkoutAssignmentSegment> = { pace };
    if (segment.distanceMeters) {
      const paceSecPerKm = paceSecPerKmFromSegment(pace);
      if (paceSecPerKm !== null) {
        patch.durationSeconds = Math.round(secondsFromDistanceAndPace(segment.distanceMeters, paceSecPerKm));
      }
    }
    onChange(patch);
  }

  return (
    <div className="segment-editor-card">
      <div className="segment-editor-head">
        <span className="segment-editor-index">{String(index + 1).padStart(2, "0")}</span>
        <input
          className="input segment-editor-label"
          value={segment.label}
          onChange={(e) => onChange({ label: e.target.value })}
          aria-label={en ? "Block label" : "段落名稱"}
        />
        <div className="row" style={{ gap: 2 }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-icon"
            disabled={index === 0}
            onClick={() => onMove(-1)}
            aria-label={en ? "Move up" : "上移"}
          >
            <Icon name="chevron-up" size={14} />
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-icon"
            disabled={index === total - 1}
            onClick={() => onMove(1)}
            aria-label={en ? "Move down" : "下移"}
          >
            <Icon name="chevron-down" size={14} />
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-icon"
            onClick={onRemove}
            aria-label={en ? "Remove block" : "移除段落"}
          >
            <Icon name="trash" size={14} />
          </button>
        </div>
      </div>

      <div className="segment-editor-body">
        {(segment.kind === "warmup" || segment.kind === "jog" || segment.kind === "cooldown") && (
          <>
            <div className="grid-2">
              <Field label={en ? "Duration (min)" : "時長（分鐘）"} hint={en ? "Auto-fills from distance × pace" : "會依距離 × 配速自動換算"}>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={0.5}
                  value={segment.durationSeconds ? segment.durationSeconds / 60 : ""}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    handleDurationChange(e.target.value === "" ? undefined : Math.round(v * 60));
                  }}
                />
              </Field>
              <Field label={en ? "Distance (m, optional)" : "距離（公尺，選填）"}>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={50}
                  value={segment.distanceMeters ?? ""}
                  onChange={(e) =>
                    handleDistanceChange(e.target.value === "" ? undefined : Number(e.target.value))
                  }
                />
              </Field>
            </div>
            <PaceRangeField locale={locale} min={paceParts.min} max={paceParts.max} onChange={handlePaceChange} />
          </>
        )}

        {segment.kind === "interval" && (
          <>
            <Segmented
              value={hasCustomReps ? "custom" : "uniform"}
              onChange={(next) =>
                next === "uniform"
                  ? onChange({
                      distancesMeters: undefined,
                      distanceMeters: segment.distanceMeters ?? 400,
                      repetitions: segment.repetitions ?? 6,
                    })
                  : onChange({
                      repetitions: undefined,
                      distanceMeters: undefined,
                      distancesMeters: segment.distancesMeters?.length
                        ? segment.distancesMeters
                        : [segment.distanceMeters ?? 400],
                    })
              }
              options={[
                { value: "uniform", label: en ? "Same distance each rep" : "每趟距離相同" },
                { value: "custom", label: en ? "Different distance per rep" : "每趟距離不同" },
              ]}
            />

            {!hasCustomReps ? (
              <div className="grid-2">
                <Field label={en ? "Reps" : "趟數"}>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={segment.repetitions ?? ""}
                    onChange={(e) =>
                      onChange({ repetitions: e.target.value === "" ? undefined : Number(e.target.value) })
                    }
                  />
                </Field>
                <Field label={en ? "Distance per rep (m)" : "每趟距離（公尺）"}>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step={50}
                    value={segment.distanceMeters ?? ""}
                    onChange={(e) =>
                      onChange({ distanceMeters: e.target.value === "" ? undefined : Number(e.target.value) })
                    }
                  />
                </Field>
              </div>
            ) : (
              <div className="stack-sm">
                {(segment.distancesMeters ?? []).map((dist, repIndex) => (
                  <div className="row" key={repIndex} style={{ gap: 8 }}>
                    <span className="field-hint" style={{ minWidth: 56 }}>
                      {en ? `Rep ${repIndex + 1}` : `第 ${repIndex + 1} 趟`}
                    </span>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step={50}
                      value={dist}
                      onChange={(e) => {
                        const next = [...(segment.distancesMeters ?? [])];
                        next[repIndex] = Number(e.target.value) || 0;
                        onChange({ distancesMeters: next });
                      }}
                    />
                    <span className="field-hint">m</span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm btn-icon"
                      disabled={(segment.distancesMeters?.length ?? 0) <= 1}
                      onClick={() =>
                        onChange({
                          distancesMeters: (segment.distancesMeters ?? []).filter((_, i) => i !== repIndex),
                        })
                      }
                      aria-label={en ? "Remove rep" : "移除這一趟"}
                    >
                      <Icon name="x" size={13} />
                    </button>
                  </div>
                ))}
                <Button
                  size="sm"
                  onClick={() =>
                    onChange({
                      distancesMeters: [...(segment.distancesMeters ?? []), segment.distancesMeters?.at(-1) ?? 400],
                    })
                  }
                >
                  <Icon name="plus" size={13} />
                  {en ? "Add a rep" : "新增一趟"}
                </Button>
              </div>
            )}

            <div className="grid-2">
              <DurationField
                label={en ? "Rest between reps" : "組間休息"}
                locale={locale}
                seconds={segment.restSeconds}
                onChange={(s) => onChange({ restSeconds: s })}
              />
              <PaceRangeField
                locale={locale}
                min={paceParts.min}
                max={paceParts.max}
                onChange={(min, max) => onChange({ pace: composePace(min, max) })}
              />
            </div>
            {estimate.seconds !== null && (
              <div className="field-hint">
                {en ? `≈ Estimated time for this block: ${formatSecPerKmToMMSS(estimate.seconds)}` : `≈ 該段預估時間 ${formatSecPerKmToMMSS(estimate.seconds)}`}
              </div>
            )}
          </>
        )}

        {(segment.kind === "recovery" || segment.kind === "rest") && (
          <DurationField
            label={en ? "Duration" : "時長"}
            locale={locale}
            seconds={segment.durationSeconds}
            onChange={(s) => onChange({ durationSeconds: s })}
          />
        )}
      </div>
    </div>
  );
}

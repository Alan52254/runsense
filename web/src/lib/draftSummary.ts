/** A Schedule Draft card read as a week: one summary, then one line per day.
 *
 *  Pure: takes the card payload and its preview, returns what the card
 *  prints, so the coach reads "4 天 · 28 km · ACWR 0.00 → 0.67" before any
 *  per-day detail. */

import type { PlanBlockWire, PlanCardPayload, PlanPreviewWire } from "../data/apiClient.ts";
import { formatDistanceMeters, formatPaceSec } from "./figureFormat.ts";

export interface DraftDayLine {
  key: string;
  date: string | null;
  /** "10/27 週二" */
  dateLabel: string;
  /** "輕鬆跑" */
  type: string;
  /** "7 km @ 5:55 /km"; null when the day has no measured run */
  distancePace: string | null;
  /** "傍晚 18:00"; null when the draft gave no time of day */
  slot: string | null;
  /** main-set metres for the summary total */
  meters: number;
  removed: boolean;
}

export interface DraftWeekSummary {
  days: DraftDayLine[];
  /** days that will be scheduled (not removed) */
  dayCount: number;
  totalKm: number;
  /** ACWR today and on the last scheduled day with this week in place */
  acwrBefore: number | null;
  acwrAfter: number | null;
}

const WEEKDAY = "日一二三四五六";

export function draftDateLabel(iso: string | null): string {
  if (!iso) return "未定日期";
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${Number(d)} 週${WEEKDAY[new Date(`${iso}T00:00:00`).getDay()]}`;
}

/** "建議傍晚 18:00 跑（預報 12.8°C）" -> "傍晚 18:00" */
export function slotFrom(text: string | null | undefined): string | null {
  const match = text?.match(/建議\s*(\S+?\s*\d{1,2}:\d{2})\s*跑/);
  return match ? match[1] : null;
}

function mainBlock(blocks: PlanBlockWire[]): PlanBlockWire | null {
  return blocks.find((b) => b.distance_m) ?? blocks[0] ?? null;
}

function blocksMeters(blocks: PlanBlockWire[]): number {
  return blocks.reduce((sum, b) => sum + (b.distance_m ?? 0) * b.reps, 0);
}

function distancePaceText(blocks: PlanBlockWire[]): string | null {
  const b = mainBlock(blocks);
  if (!b) return null;
  const amount = b.distance_m
    ? formatDistanceMeters(b.distance_m)
    : b.duration_s
      ? `${Math.round(b.duration_s / 60)} 分鐘`
      : null;
  if (!amount) return null;
  const reps = b.reps > 1 ? ` × ${b.reps}` : "";
  const pace = b.target_s_per_km ? ` @ ${formatPaceSec(b.target_s_per_km)} /km` : "";
  return `${amount}${reps}${pace}`;
}

export function summarizeDraftWeek(payload: PlanCardPayload, preview: PlanPreviewWire | null | undefined): DraftWeekSummary {
  const rows = new Map((preview?.rows ?? []).map((r) => [r.key, r]));
  const week = new Map((payload.schedule_draft?.week ?? []).map((w) => [w.date, w]));
  let acwrBefore: number | null = null;
  let acwrAfter: number | null = null;
  let lastOn = "";

  const days = payload.plan.days.map((day): DraftDayLine => {
    const entry = rows.get(day.key)?.entries.find((e) => e.status !== "skip_completed") ?? rows.get(day.key)?.entries[0];
    const item = entry?.items[0];
    const blocks = item?.blocks ?? [];
    const load = entry?.projected_load;
    if (load && !day.removed) {
      acwrBefore ??= load.before;
      if (load.on >= lastOn) {
        lastOn = load.on;
        acwrAfter = load.after;
      }
    }
    return {
      key: day.key,
      date: day.date,
      dateLabel: draftDateLabel(day.date),
      type: item?.record?.intensity_label ?? item?.title ?? day.items[0]?.title ?? "訓練",
      distancePace: distancePaceText(blocks),
      slot: slotFrom(week.get(day.date ?? "")?.weather_note) ?? slotFrom(day.source),
      meters: blocksMeters(blocks),
      removed: day.removed,
    };
  });

  const kept = days.filter((d) => !d.removed);
  return {
    days,
    dayCount: kept.length,
    totalKm: Math.round(kept.reduce((sum, d) => sum + d.meters, 0) / 100) / 10,
    acwrBefore,
    acwrAfter,
  };
}

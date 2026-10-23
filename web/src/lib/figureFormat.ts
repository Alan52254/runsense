/** Pure number formatting for run figures (pace, duration, distance). */

const DASH = "—";

function clock(totalSec: number): string {
  const s = Math.round(totalSec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** Seconds per km -> "m:ss"; "—" when missing or not a plausible pace. */
export function formatPaceSec(secPerKm: number | null | undefined): string {
  if (!secPerKm || secPerKm <= 0 || secPerKm > 3600) return DASH;
  const total = Math.round(secPerKm);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** "6:00–6:20" */
export function formatPaceRangeSec(lo: number, hi: number): string {
  return `${formatPaceSec(lo)}–${formatPaceSec(hi)}`;
}

/** Seconds -> "m:ss" or "h:mm:ss". */
export function formatDurationSec(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return DASH;
  return clock(seconds);
}

/** Minutes -> "1 小時 3 分" / "1 hr 3 min". */
export function formatDurationMin(minutes: number, locale: "zh-TW" | "en" = "zh-TW"): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (locale === "en") return h > 0 ? `${h} hr ${m} min` : `${m} min`;
  return h > 0 ? `${h} 小時 ${m} 分` : `${m} 分`;
}

interface DistanceParts {
  value: string;
  unit: "m" | "km";
}

function kmParts(km: number): DistanceParts {
  return { value: String(Number(km.toFixed(2))), unit: "km" };
}

function distanceParts(meters: number): DistanceParts {
  if (meters >= 1000) return kmParts(meters / 1000);
  return { value: String(Math.round(meters)), unit: "m" };
}

/** 800 -> "800 m", 10500 -> "10.5 km". */
export function formatDistanceMeters(meters: number | null | undefined): string {
  if (meters === null || meters === undefined) return DASH;
  const p = distanceParts(meters);
  return `${p.value} ${p.unit}`;
}

export function formatDistanceKm(km: number | null | undefined): string {
  if (km === null || km === undefined) return DASH;
  const p = kmParts(km);
  return `${p.value} ${p.unit}`;
}

export type FigureSpec =
  | { kind: "pace"; secPerKm: number | null | undefined; secPerKmHi?: number }
  | { kind: "duration"; seconds: number | null | undefined }
  | { kind: "distance"; meters: number | null | undefined };

/** Value and unit as separate strings so the unit can be styled quieter. */
export function formatByKind(spec: FigureSpec): { value: string; unit: string } {
  switch (spec.kind) {
    case "pace": {
      const value =
        spec.secPerKmHi !== undefined && spec.secPerKm
          ? formatPaceRangeSec(spec.secPerKm, spec.secPerKmHi)
          : formatPaceSec(spec.secPerKm);
      return { value, unit: value === DASH ? "" : "/km" };
    }
    case "duration":
      return { value: formatDurationSec(spec.seconds), unit: "" };
    case "distance": {
      if (spec.meters === null || spec.meters === undefined) return { value: DASH, unit: "" };
      return distanceParts(spec.meters);
    }
  }
}

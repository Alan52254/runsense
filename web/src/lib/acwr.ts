/** The one vocabulary for the acute:chronic workload ratio.
 *
 *  Every screen names the ratio "ACWR 負荷比" (just "ACWR" in a tight chip)
 *  and describes where it sits with the same four zone words, so a runner
 *  and a coach never meet 比值 / 偏低 / 低於基準 for the same number. */

type Locale = "zh-TW" | "en";

export type AcwrZone = "low" | "safe" | "high" | "alert";

/** Full name, for labels and table headings. */
export const ACWR_NAME: Record<Locale, string> = { "zh-TW": "ACWR 負荷比", en: "ACWR load ratio" };
/** Short name, for chips and narrow columns. */
export const ACWR_SHORT = "ACWR";

/** The ratio, or null when it says nothing yet. A ratio of 0 only happens
 *  with no acute load at all (a new athlete, London in the demo), and
 *  printing "0.00" would read as a real, very low load. */
export function usableAcwr(ratio: number | null | undefined): number | null {
  return ratio !== null && ratio !== undefined && ratio > 0 ? ratio : null;
}

/** Acute:chronic workload ratio band; null when there is no ratio yet. */
export function deriveAcwrZone(ratio: number | null): AcwrZone | null {
  if (usableAcwr(ratio) === null || ratio === null) return null;
  if (ratio < 0.8) return "low";
  if (ratio <= 1.3) return "safe";
  if (ratio <= 1.5) return "high";
  return "alert";
}

const ZONE_LABEL: Record<AcwrZone, Record<Locale, string>> = {
  low: { "zh-TW": "低於安全區間", en: "below safe range" },
  safe: { "zh-TW": "安全區間內", en: "in safe range" },
  high: { "zh-TW": "高於安全區間", en: "above safe range" },
  alert: { "zh-TW": "遠高於安全區間", en: "well above safe range" },
};

const NO_RATIO: Record<Locale, string> = { "zh-TW": "資料不足", en: "insufficient data" };

export function acwrZoneLabel(zone: AcwrZone | null, locale: Locale): string {
  return zone === null ? NO_RATIO[locale] : ZONE_LABEL[zone][locale];
}

/** "0.74", or "資料不足" when there is no usable ratio. */
export function acwrValueText(ratio: number | null | undefined, locale: Locale): string {
  const r = usableAcwr(ratio);
  return r === null ? NO_RATIO[locale] : r.toFixed(2);
}

/** "ACWR 0.11 · 低於安全區間" -- the short form used in chips and badges;
 *  "ACWR 資料不足" when there is no usable ratio. */
export function acwrChipText(ratio: number | null, locale: Locale): string {
  const r = usableAcwr(ratio);
  if (r === null) return `${ACWR_SHORT} ${NO_RATIO[locale]}`;
  return `${ACWR_SHORT} ${r.toFixed(2)} · ${acwrZoneLabel(deriveAcwrZone(r), locale)}`;
}

/** Older server copy that still says 負荷偏低 / 負荷偏高, in the shared words. */
export function normalizeLoadWording(text: string): string {
  return text
    .replace(/近期負荷偏低/g, `${ACWR_NAME["zh-TW"]}${ZONE_LABEL.low["zh-TW"]}`)
    .replace(/近期負荷偏高/g, `${ACWR_NAME["zh-TW"]}${ZONE_LABEL.high["zh-TW"]}`);
}

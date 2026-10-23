/* The one way the app words a climate pace shift.
 *
 * speed_loss_pct (backend weather_pace.py) is the % of running speed the
 * weather costs: positive means slower, negative means a cooler-than-normal
 * day gives some back. Every surface that prints it -- ticker, hero pill,
 * conditions drawer, health coach figures -- goes through paceShiftText, so
 * the same day never reads as a loss in one place and a bonus in another. */

type Locale = "zh-TW" | "en";

/** "慢 0.8%" / "快 0.8%" / "不受影響". */
export function paceShiftText(pct: number, locale: Locale): string {
  const en = locale === "en";
  const size = Math.abs(pct).toFixed(1);
  if (size === "0.0") return en ? "no change" : "不受影響";
  if (pct > 0) return en ? `${size}% slower` : `慢 ${size}%`;
  return en ? `${size}% faster` : `快 ${size}%`;
}

export type ClimateSlot = "morning" | "midday" | "evening";

/** The slot times the server estimates (backend routes/weather.py
 *  _TIME_OF_DAY_HOURS). The wire's `hour` is an int, so 18:30 arrives as 18;
 *  the label is the reliable key. */
const SLOT_TIME: Record<ClimateSlot, string> = { morning: "06:00", midday: "12:00", evening: "18:30" };

/** Which moment a climate figure describes: "現在", or "18:30 時段" for a
 *  time-of-day slot. */
export function climateMomentLabel(slot: ClimateSlot | null, locale: Locale): string {
  if (slot === null) return locale === "en" ? "now" : "現在";
  return locale === "en" ? `${SLOT_TIME[slot]} slot` : `${SLOT_TIME[slot]} 時段`;
}

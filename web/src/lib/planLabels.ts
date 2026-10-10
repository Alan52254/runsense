/** Athlete-facing names for the reviewed workout options.
 *
 *  Shared so every surface that shows an option calls it the same thing.
 *  These are the Athlete's words: no ranking, model, or retrieval vocabulary
 *  belongs in this file.
 */

export type Locale = "zh-TW" | "en";

export const PLAN_TYPE_LABEL: Record<string, Record<Locale, string>> = {
  REST_DAY: { "zh-TW": "休息日", en: "Rest day" },
  REST_AND_SEEK_CARE: { "zh-TW": "休息並尋求評估", en: "Rest and seek assessment" },
  RECOVERY_RUN: { "zh-TW": "恢復跑", en: "Recovery run" },
  EASY_RUN: { "zh-TW": "輕鬆跑", en: "Easy run" },
  STEADY_RUN: { "zh-TW": "穩定跑", en: "Steady run" },
};

export function planTypeLabel(workoutType: string, locale: Locale): string {
  return PLAN_TYPE_LABEL[workoutType]?.[locale] ?? workoutType;
}

/** How much of the plan is tailored to this Athlete.
 *
 *  When there is not yet enough of their own data, RunSense says so and gives
 *  the conservative ordering, rather than quietly handing over a different
 *  quality of answer.
 */
export function personalisationLabel(
  confidence: number | null,
  abstained: boolean,
  locale: Locale,
): { text: string; isConservative: boolean } {
  if (abstained || confidence === null) {
    return {
      isConservative: true,
      text:
        locale === "en"
          ? "Conservative — not enough of your data yet"
          : "保守建議 — 你的資料還不足以個人化",
    };
  }
  return {
    isConservative: false,
    text:
      locale === "en"
        ? `Personalised to you: ${(confidence * 100).toFixed(0)}%`
        : `已依你的資料調整：${(confidence * 100).toFixed(0)}%`,
  };
}

/** What a stated set of conditions costs, in the Athlete's terms. */
export function conditionsCostLabel(
  speedLossPct: number | null,
  locale: Locale,
): string | null {
  if (speedLossPct === null) return null;
  const en = locale === "en";
  if (Math.abs(speedLossPct) < 0.05) {
    return en ? "About the same as a typical evening" : "與平常傍晚差不多";
  }
  if (speedLossPct > 0) {
    return en
      ? `About ${speedLossPct.toFixed(1)}% slower than a typical evening`
      : `比平常傍晚大約慢 ${speedLossPct.toFixed(1)}%`;
  }
  return en
    ? `About ${Math.abs(speedLossPct).toFixed(1)}% faster than a typical evening`
    : `比平常傍晚大約快 ${Math.abs(speedLossPct).toFixed(1)}%`;
}

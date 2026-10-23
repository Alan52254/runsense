/** What kind of run a history row was, read from its recorded structure.
 *
 *  Only the segments the record actually carries decide the answer; a row
 *  with no structure gets no chip rather than a guessed one. */

export type Locale = "zh-TW" | "en";
export type HistoryWorkoutKind = "interval" | "tempo" | "easy";

const LABEL: Record<HistoryWorkoutKind, Record<Locale, string>> = {
  interval: { "zh-TW": "間歇", en: "Intervals" },
  tempo: { "zh-TW": "節奏跑", en: "Tempo" },
  easy: { "zh-TW": "慢跑", en: "Easy" },
};

const EASY_KINDS = new Set(["jog", "recovery", "warmup", "cooldown", "rest"]);

/** Interval beats tempo beats easy: a session with any repeat block is an
 *  interval session, whatever warm-up surrounds it. The wire also carries
 *  "tempo", which the client segment union does not name, so kinds are
 *  compared as plain strings. */
export function historyWorkoutKind(structure: readonly { kind: string }[] | null | undefined): HistoryWorkoutKind | null {
  if (!structure || structure.length === 0) return null;
  const kinds = structure.map((segment) => String(segment.kind));
  if (kinds.includes("interval")) return "interval";
  if (kinds.includes("tempo")) return "tempo";
  if (kinds.every((kind) => EASY_KINDS.has(kind))) return "easy";
  return null;
}

export function historyWorkoutKindLabel(kind: HistoryWorkoutKind, locale: Locale): string {
  return LABEL[kind][locale];
}

/** A row worth a 查看分析 shortcut: a synced watch recording of a structured
 *  session. The rep-by-rep analysis needs the watch's own .fit file, and only
 *  rows imported from a watch carry its numeric activity id; rows rebuilt
 *  from summaries (no file, telemetry 404) get no shortcut. */
export function isAnalysableRow(row: {
  provider: string;
  providerActivityId: string | null;
  syncState: string;
  structure: readonly { kind: string }[] | null | undefined;
}): boolean {
  const kind = historyWorkoutKind(row.structure);
  return row.provider === "garmin"
    && row.syncState === "SYNCED"
    && /^\d+$/.test(row.providerActivityId ?? "")
    && (kind === "interval" || kind === "tempo");
}

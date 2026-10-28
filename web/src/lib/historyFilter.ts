/** Which 歷程回顧 rows each filter chip shows. Order is always kept. */
import { isAnalysableRow } from "./historyWorkoutKind.ts";

export type HistoryFilter = "all" | "pending" | "failed" | "duplicate" | "analysable";

interface FilterableRow {
  provider: string;
  providerActivityId: string | null;
  syncState: string;
  duplicateCandidateOf: string | null;
  structure: readonly { kind: string }[] | null | undefined;
}

export function filterHistoryRows<T extends FilterableRow>(rows: readonly T[], filter: HistoryFilter): T[] {
  switch (filter) {
    case "pending":
      return rows.filter((a) => a.syncState === "LOCAL_ONLY" || a.syncState === "SYNCING");
    case "failed":
      return rows.filter((a) => a.syncState === "FAILED_RETRYABLE" || a.syncState === "FAILED_TERMINAL");
    case "duplicate":
      return rows.filter((a) => a.duplicateCandidateOf !== null);
    case "analysable":
      return rows.filter(isAnalysableRow);
    default:
      return [...rows];
  }
}

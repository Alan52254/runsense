// See design.md Decision 6/7: this is a "sync coordinator", not a
// background sync worker -- it only runs while explicitly started (i.e.
// while the app process is active or has just been reopened). It does not
// implement OS-level background execution, and the 95%/30s SLA (spec.md
// "Offline Sync Queue and Delivery SLA") is scoped to while it is active.

import type { ApiClient, LocalActivityRecord } from "./types.ts";
import type { LocalActivityStore } from "./localStore.ts";

const DEFAULT_CONCURRENCY = 20;

export interface SyncOutcome {
  localId: string;
  outcome: "synced" | "already_synced" | "retryable_failure" | "terminal_failure";
  errorCode?: string;
}

async function runWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  worker: (item: T) => Promise<R>
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let nextIndex = 0;

  async function runOne(): Promise<void> {
    while (nextIndex < items.length) {
      const currentIndex = nextIndex++;
      results[currentIndex] = await worker(items[currentIndex]);
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, items.length) }, () => runOne());
  await Promise.all(workers);
  return results;
}

export class SyncCoordinator {
  private intervalHandle: ReturnType<typeof setInterval> | null = null;
  private readonly store: LocalActivityStore;
  private readonly apiClient: ApiClient;
  private readonly concurrency: number;

  constructor(store: LocalActivityStore, apiClient: ApiClient, concurrency: number = DEFAULT_CONCURRENCY) {
    this.store = store;
    this.apiClient = apiClient;
    this.concurrency = concurrency;
  }

  /** Starts periodic syncing. Only meaningful while the process is alive --
   *  calling this is what "the coordinator is active" means (see spec.md). */
  start(accountId: string, intervalMs: number): void {
    if (this.intervalHandle !== null) return;
    this.intervalHandle = setInterval(() => {
      void this.syncOnce(accountId);
    }, intervalMs);
  }

  stop(): void {
    if (this.intervalHandle !== null) {
      clearInterval(this.intervalHandle);
      this.intervalHandle = null;
    }
  }

  /** Processes the current pending queue for an account in one pass. */
  async syncOnce(accountId: string): Promise<SyncOutcome[]> {
    const pending = this.store.listPendingForAccount(accountId);
    return runWithConcurrency(pending, this.concurrency, (record) => this.syncOne(record));
  }

  private async syncOne(record: LocalActivityRecord): Promise<SyncOutcome> {
    this.store.markSyncing(record.localId);

    let response;
    try {
      response = await this.apiClient.createActivity({
        client_mutation_id: record.clientMutationId,
        duration_minutes: record.durationMinutes,
        rpe: record.rpe,
        performed_at: record.performedAtUtc,
      });
    } catch {
      // Network error: retryable.
      this.store.markFailedRetryable(record.localId, "NETWORK_ERROR");
      return { localId: record.localId, outcome: "retryable_failure", errorCode: "NETWORK_ERROR" };
    }

    if (response.status === 201 || response.status === 200) {
      const body = response.body ?? {};
      const serverId = String(body.id);
      const serverVersion = Number(body.server_version ?? 1);
      this.store.markSynced(record.localId, serverId, serverVersion);
      return {
        localId: record.localId,
        outcome: response.status === 201 ? "synced" : "already_synced",
      };
    }

    if (response.status >= 500) {
      this.store.markFailedRetryable(record.localId, `HTTP_${response.status}`);
      return {
        localId: record.localId,
        outcome: "retryable_failure",
        errorCode: `HTTP_${response.status}`,
      };
    }

    // Any other 4xx -- including a 409 idempotency-conflict, which should
    // never legitimately occur for a record whose client_mutation_id is its
    // own immutable local id (see design.md Decision 3) -- is treated as
    // non-retryable: the payload driving this request will not change on
    // its own, so retrying cannot succeed. See design.md Decision 6.
    const errorCode =
      (response.body?.error as string | undefined) ?? `HTTP_${response.status}`;
    this.store.markFailedTerminal(record.localId, errorCode);
    return { localId: record.localId, outcome: "terminal_failure", errorCode };
  }
}

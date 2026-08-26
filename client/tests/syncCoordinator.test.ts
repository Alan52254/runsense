import { describe, it, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalActivityStore } from "../src/localStore.ts";
import { SyncCoordinator } from "../src/syncCoordinator.ts";
import { FakeApiClient } from "./fakeApiClient.ts";

const tempDirs: string[] = [];

function tempDbPath(): string {
  const dir = mkdtempSync(join(tmpdir(), "runsense-sync-coordinator-"));
  tempDirs.push(dir);
  return join(dir, "local.sqlite");
}

after(() => {
  for (const dir of tempDirs) rmSync(dir, { recursive: true, force: true });
});

describe("SyncCoordinator", () => {
  it("marks a record SYNCED with the server id/version on success", async () => {
    const store = new LocalActivityStore(tempDbPath());
    const record = store.createLocalOnly("account-1", {
      durationMinutes: 45,
      rpe: 6,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });

    const api = new FakeApiClient();
    const coordinator = new SyncCoordinator(store, api);
    const outcomes = await coordinator.syncOnce("account-1");

    assert.equal(outcomes.length, 1);
    assert.equal(outcomes[0].outcome, "synced");
    const reloaded = store.get(record.localId)!;
    assert.equal(reloaded.syncState, "SYNCED");
    assert.match(reloaded.serverId!, /^server-/);
    assert.equal(reloaded.serverVersion, 1);
    store.close();
  });

  it("TC-SYNC-TERMINAL-001: a non-retryable 4xx stops automatic retry", async () => {
    const store = new LocalActivityStore(tempDbPath());
    const record = store.createLocalOnly("account-1", {
      durationMinutes: 45,
      rpe: 6,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });

    const api = new FakeApiClient(0, new Set(), new Set([record.clientMutationId]));
    const coordinator = new SyncCoordinator(store, api);

    const first = await coordinator.syncOnce("account-1");
    assert.equal(first[0].outcome, "terminal_failure");
    const afterFirst = store.get(record.localId)!;
    assert.equal(afterFirst.syncState, "FAILED_TERMINAL");
    assert.equal(afterFirst.lastErrorCode, "SIMULATED_TERMINAL_FAILURE");

    const callsBeforeSecondPass = api.callCount;
    const second = await coordinator.syncOnce("account-1");
    // FAILED_TERMINAL is not in the pending set, so a second pass must not
    // attempt it again at all.
    assert.equal(second.length, 0);
    assert.equal(api.callCount, callsBeforeSecondPass);
    assert.equal(store.get(record.localId)!.syncState, "FAILED_TERMINAL");
    store.close();
  });

  it("a retryable failure is retried and succeeds on a later pass", async () => {
    const store = new LocalActivityStore(tempDbPath());
    const record = store.createLocalOnly("account-1", {
      durationMinutes: 30,
      rpe: 4,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });

    const api = new FakeApiClient(0, new Set([record.clientMutationId]));
    const coordinator = new SyncCoordinator(store, api);

    const first = await coordinator.syncOnce("account-1");
    assert.equal(first[0].outcome, "retryable_failure");
    assert.equal(store.get(record.localId)!.syncState, "FAILED_RETRYABLE");

    const second = await coordinator.syncOnce("account-1");
    assert.equal(second[0].outcome, "synced");
    assert.equal(store.get(record.localId)!.syncState, "SYNCED");
    store.close();
  });

  it("TC-SYNC-002: >=95/100 queued mutations sync within 30s with zero duplicates and zero loss", async () => {
    const store = new LocalActivityStore(tempDbPath());

    const clientMutationIds: string[] = [];
    for (let i = 0; i < 100; i++) {
      const record = store.createLocalOnly("account-1", {
        durationMinutes: 20 + i,
        rpe: (i % 10) + 1,
        performedAtUtc: "2026-08-07T09:15:00Z",
      });
      clientMutationIds.push(record.clientMutationId);
    }

    // 5 records fail their first attempt (retryable) to prove the SLA holds
    // even with realistic transient failures, not just a clean run.
    const failFirstAttemptFor = new Set(clientMutationIds.slice(0, 5));
    const api = new FakeApiClient(5, failFirstAttemptFor);
    const coordinator = new SyncCoordinator(store, api, 20);

    const start = Date.now();
    let syncedCount = store
      .listForAccount("account-1")
      .filter((r) => r.syncState === "SYNCED").length;
    let pass = 0;
    const budgetMs = 30_000;
    while (syncedCount < 95 && Date.now() - start < budgetMs && pass < 10) {
      await coordinator.syncOnce("account-1");
      syncedCount = store.listForAccount("account-1").filter((r) => r.syncState === "SYNCED").length;
      pass += 1;
    }
    const elapsedMs = Date.now() - start;

    const allRecords = store.listForAccount("account-1");
    const terminalCount = allRecords.filter((r) => r.syncState === "FAILED_TERMINAL").length;
    const lostCount = allRecords.filter(
      (r) => !["SYNCED", "LOCAL_ONLY", "FAILED_RETRYABLE", "SYNCING"].includes(r.syncState)
    ).length;

    assert.ok(elapsedMs < budgetMs, `expected < ${budgetMs}ms, got ${elapsedMs}ms`);
    assert.ok(syncedCount >= 95, `expected >=95 synced, got ${syncedCount}`);
    assert.equal(terminalCount, 0); // zero unexpected non-retryable outcomes
    assert.equal(lostCount, 0); // zero silently lost records
    assert.equal(api.distinctServerIdCount(), syncedCount); // zero duplicate canonical rows
    store.close();
  });

  it("a 409 idempotency conflict is treated as a non-retryable terminal failure", async () => {
    const store = new LocalActivityStore(tempDbPath());
    const record = store.createLocalOnly("account-1", {
      durationMinutes: 45,
      rpe: 6,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });

    const api = new FakeApiClient(0, new Set(), new Set(), new Set([record.clientMutationId]));
    const coordinator = new SyncCoordinator(store, api);

    const first = await coordinator.syncOnce("account-1");
    assert.equal(first[0].outcome, "terminal_failure");
    assert.equal(first[0].errorCode, "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD");
    const afterFirst = store.get(record.localId)!;
    assert.equal(afterFirst.syncState, "FAILED_TERMINAL");

    const callsBeforeSecondPass = api.callCount;
    const second = await coordinator.syncOnce("account-1");
    assert.equal(second.length, 0);
    assert.equal(api.callCount, callsBeforeSecondPass);
    store.close();
  });

  it("start() polls on the given interval and stop() halts further polling", async () => {
    const store = new LocalActivityStore(tempDbPath());
    store.createLocalOnly("account-1", {
      durationMinutes: 10,
      rpe: 2,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });

    const api = new FakeApiClient();
    const coordinator = new SyncCoordinator(store, api);

    coordinator.start("account-1", 20);
    try {
      // Poll until the record syncs rather than sleeping a fixed guess --
      // avoids flakiness from scheduler jitter while still proving start()
      // actually drives syncOnce() on its own, with no manual calls here.
      const deadline = Date.now() + 5_000;
      let synced = store.get(store.listForAccount("account-1")[0].localId)!;
      while (synced.syncState !== "SYNCED" && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 10));
        synced = store.get(synced.localId)!;
      }
      assert.equal(synced.syncState, "SYNCED");
    } finally {
      coordinator.stop();
    }

    const callsAfterStop = api.callCount;
    await new Promise((resolve) => setTimeout(resolve, 60));
    assert.equal(api.callCount, callsAfterStop, "no further calls should happen after stop()");

    // Calling start() again after stop() must resume polling (not be a no-op
    // forever) -- exercises the intervalHandle-reset path.
    store.createLocalOnly("account-1", {
      durationMinutes: 15,
      rpe: 3,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });
    coordinator.start("account-1", 20);
    try {
      const deadline = Date.now() + 5_000;
      let pending = store.listPendingForAccount("account-1");
      while (pending.length > 0 && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 10));
        pending = store.listPendingForAccount("account-1");
      }
      assert.equal(pending.length, 0);
    } finally {
      coordinator.stop();
    }
    store.close();
  });

  it("start() is idempotent while already running: a second call does not create a duplicate interval", async () => {
    const store = new LocalActivityStore(tempDbPath());
    store.createLocalOnly("account-1", {
      durationMinutes: 10,
      rpe: 2,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });

    const api = new FakeApiClient();
    const coordinator = new SyncCoordinator(store, api);

    coordinator.start("account-1", 20);
    coordinator.start("account-1", 20); // should be a no-op: interval already set
    try {
      await new Promise((resolve) => setTimeout(resolve, 100));
      // A single interval firing every 20ms for 100ms fires ~5 times; two
      // independent intervals would double that. There's only one record to
      // sync, so callCount bounds the number of ticks that actually ran.
      assert.ok(api.callCount <= 6, `expected <=6 calls from one interval, got ${api.callCount}`);
    } finally {
      coordinator.stop();
    }
    store.close();
  });
});

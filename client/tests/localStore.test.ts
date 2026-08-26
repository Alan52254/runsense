import { describe, it, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalActivityStore } from "../src/localStore.ts";

const tempDirs: string[] = [];

function tempDbPath(): string {
  const dir = mkdtempSync(join(tmpdir(), "runsense-local-store-"));
  tempDirs.push(dir);
  return join(dir, "local.sqlite");
}

after(() => {
  for (const dir of tempDirs) rmSync(dir, { recursive: true, force: true });
});

describe("LocalActivityStore", () => {
  it("computes session_load = duration_minutes x rpe on local insert", () => {
    const store = new LocalActivityStore(tempDbPath());
    const record = store.createLocalOnly("account-1", {
      durationMinutes: 45,
      rpe: 6,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });
    assert.equal(record.sessionLoad, 270);
    assert.equal(record.syncState, "LOCAL_ONLY");
    store.close();
  });

  it("TC-SYNC-001: a record committed locally survives the process 'restarting'", () => {
    const dbPath = tempDbPath();
    const store1 = new LocalActivityStore(dbPath);
    const created = store1.createLocalOnly("account-1", {
      durationMinutes: 30,
      rpe: 5,
      performedAtUtc: "2026-08-07T09:15:00Z",
    });
    // Simulate the process dying right after the durable commit returned,
    // before any sync attempt: just close the handle without further action.
    store1.close();

    // "Restart": a brand new store instance opens the same on-disk file.
    const store2 = new LocalActivityStore(dbPath);
    const reloaded = store2.get(created.localId);
    assert.ok(reloaded !== null);
    assert.equal(reloaded!.syncState, "LOCAL_ONLY");
    assert.equal(reloaded!.durationMinutes, 30);
    assert.equal(reloaded!.rpe, 5);
    store2.close();
  });

  it("TC-LOCAL-SEC-001: records are isolated by account_id", () => {
    const store = new LocalActivityStore(tempDbPath());
    store.createLocalOnly("account-A", {
      durationMinutes: 10,
      rpe: 3,
      performedAtUtc: "2026-08-07T09:00:00Z",
    });
    store.createLocalOnly("account-A", {
      durationMinutes: 20,
      rpe: 4,
      performedAtUtc: "2026-08-07T10:00:00Z",
    });
    store.createLocalOnly("account-B", {
      durationMinutes: 99,
      rpe: 9,
      performedAtUtc: "2026-08-07T11:00:00Z",
    });

    const accountARecords = store.listForAccount("account-A");
    const accountBRecords = store.listForAccount("account-B");

    assert.equal(accountARecords.length, 2);
    assert.equal(accountBRecords.length, 1);
    assert.ok(accountARecords.every((r) => r.accountId === "account-A"));
    assert.ok(accountBRecords.every((r) => r.accountId === "account-B"));
    // Switching accounts on-device shows zero rows from the previous account.
    assert.ok(!accountARecords.some((r) => r.durationMinutes === 99));
    store.close();
  });

  it("rejects an out-of-range rpe at the storage layer", () => {
    const store = new LocalActivityStore(tempDbPath());
    assert.throws(() =>
      store.createLocalOnly("account-1", {
        durationMinutes: 10,
        rpe: 11,
        performedAtUtc: "2026-08-07T09:00:00Z",
      })
    );
    store.close();
  });
});

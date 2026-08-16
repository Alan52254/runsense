// Local durable persistence. A write completes before save confirmation, and
// athlete namespaces isolate records on the shared device.
//
// Uses node:sqlite (built-in, no native compilation) rather than a
// third-party binding, and forces WAL + FULL synchronous so a committed
// write actually survives a killed process -- the property TC-SYNC-001
// depends on.

import { DatabaseSync } from "node:sqlite";
import { randomUUID } from "node:crypto";
import type { CreateActivityInput, LocalActivityRecord, SyncState } from "./types.ts";

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS completed_activities_local (
  local_id            TEXT PRIMARY KEY,
  account_id          TEXT NOT NULL,
  client_mutation_id  TEXT NOT NULL UNIQUE,
  duration_minutes    REAL NOT NULL,
  rpe                 INTEGER NOT NULL CHECK (rpe BETWEEN 1 AND 10),
  performed_at_utc    TEXT NOT NULL,
  session_load        REAL NOT NULL,
  created_at_local    TEXT NOT NULL,
  sync_state          TEXT NOT NULL CHECK (sync_state IN
                         ('LOCAL_ONLY','SYNCING','SYNCED','FAILED_RETRYABLE','FAILED_TERMINAL')),
  sync_attempts       INTEGER NOT NULL DEFAULT 0,
  last_error_code     TEXT,
  server_id           TEXT,
  server_version      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_local_account_state
  ON completed_activities_local(account_id, sync_state);
`;

interface Row {
  local_id: string;
  account_id: string;
  client_mutation_id: string;
  duration_minutes: number;
  rpe: number;
  performed_at_utc: string;
  session_load: number;
  created_at_local: string;
  sync_state: SyncState;
  sync_attempts: number;
  last_error_code: string | null;
  server_id: string | null;
  server_version: number | null;
}

function rowToRecord(row: Row): LocalActivityRecord {
  return {
    localId: row.local_id,
    accountId: row.account_id,
    clientMutationId: row.client_mutation_id,
    durationMinutes: row.duration_minutes,
    rpe: row.rpe,
    performedAtUtc: row.performed_at_utc,
    sessionLoad: row.session_load,
    createdAtLocal: row.created_at_local,
    syncState: row.sync_state,
    syncAttempts: row.sync_attempts,
    lastErrorCode: row.last_error_code,
    serverId: row.server_id,
    serverVersion: row.server_version,
  };
}

export class LocalActivityStore {
  private readonly db: DatabaseSync;

  constructor(dbPath: string) {
    this.db = new DatabaseSync(dbPath);
    this.db.exec("PRAGMA journal_mode = WAL;");
    this.db.exec("PRAGMA synchronous = FULL;");
    this.db.exec(SCHEMA_SQL);
  }

  close(): void {
    this.db.close();
  }

  /**
   * Durable local insert. Returns only after the write has committed to
   * disk -- callers (the UI layer, in a real app) must not show a "saved"
   * confirmation before this resolves. See spec.md "Save confirmation
   * follows durable commit".
   */
  createLocalOnly(accountId: string, input: CreateActivityInput): LocalActivityRecord {
    const localId = randomUUID();
    const sessionLoad = input.durationMinutes * input.rpe;
    const createdAtLocal = new Date().toISOString();

    const stmt = this.db.prepare(
      `INSERT INTO completed_activities_local
        (local_id, account_id, client_mutation_id, duration_minutes, rpe,
         performed_at_utc, session_load, created_at_local, sync_state, sync_attempts)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'LOCAL_ONLY', 0)`
    );
    stmt.run(
      localId,
      accountId,
      localId, // client_mutation_id: this record's own id, per tasks.md 4.3
      input.durationMinutes,
      input.rpe,
      input.performedAtUtc,
      sessionLoad,
      createdAtLocal
    );

    return this.get(localId)!;
  }

  get(localId: string): LocalActivityRecord | null {
    const row = this.db
      .prepare("SELECT * FROM completed_activities_local WHERE local_id = ?")
      .get(localId) as Row | undefined;
    return row ? rowToRecord(row) : null;
  }

  listForAccount(accountId: string): LocalActivityRecord[] {
    const rows = this.db
      .prepare(
        "SELECT * FROM completed_activities_local WHERE account_id = ? ORDER BY created_at_local"
      )
      .all(accountId) as unknown as Row[];
    return rows.map(rowToRecord);
  }

  listPendingForAccount(accountId: string): LocalActivityRecord[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM completed_activities_local
         WHERE account_id = ? AND sync_state IN ('LOCAL_ONLY', 'FAILED_RETRYABLE')
         ORDER BY created_at_local`
      )
      .all(accountId) as unknown as Row[];
    return rows.map(rowToRecord);
  }

  markSyncing(localId: string): void {
    this.db
      .prepare(
        "UPDATE completed_activities_local SET sync_state = 'SYNCING', sync_attempts = sync_attempts + 1 WHERE local_id = ?"
      )
      .run(localId);
  }

  markSynced(localId: string, serverId: string, serverVersion: number): void {
    this.db
      .prepare(
        `UPDATE completed_activities_local
         SET sync_state = 'SYNCED', server_id = ?, server_version = ?, last_error_code = NULL
         WHERE local_id = ?`
      )
      .run(serverId, serverVersion, localId);
  }

  markFailedRetryable(localId: string, errorCode: string): void {
    this.db
      .prepare(
        "UPDATE completed_activities_local SET sync_state = 'FAILED_RETRYABLE', last_error_code = ? WHERE local_id = ?"
      )
      .run(errorCode, localId);
  }

  markFailedTerminal(localId: string, errorCode: string): void {
    this.db
      .prepare(
        "UPDATE completed_activities_local SET sync_state = 'FAILED_TERMINAL', last_error_code = ? WHERE local_id = ?"
      )
      .run(errorCode, localId);
  }
}

// See openspec/changes/manual-workout-create-sync/design.md Decision 6:
// LOCAL_ONLY -> SYNCING -> SYNCED, with FAILED_RETRYABLE for network/5xx
// errors and FAILED_TERMINAL for non-retryable 4xx responses.
export type SyncState =
  | "LOCAL_ONLY"
  | "SYNCING"
  | "SYNCED"
  | "FAILED_RETRYABLE"
  | "FAILED_TERMINAL";

export interface CreateActivityInput {
  durationMinutes: number;
  rpe: number;
  performedAtUtc: string; // ISO 8601, must include timezone/UTC designator
}

export interface LocalActivityRecord {
  localId: string;
  accountId: string;
  clientMutationId: string;
  durationMinutes: number;
  rpe: number;
  performedAtUtc: string;
  sessionLoad: number;
  createdAtLocal: string;
  syncState: SyncState;
  syncAttempts: number;
  lastErrorCode: string | null;
  serverId: string | null;
  serverVersion: number | null;
}

export interface ActivityWirePayload {
  client_mutation_id: string;
  duration_minutes: number;
  rpe: number;
  performed_at: string;
}

export interface ApiResponse {
  status: number;
  body: Record<string, unknown> | null;
}

export interface ApiClient {
  createActivity(payload: ActivityWirePayload): Promise<ApiResponse>;
}

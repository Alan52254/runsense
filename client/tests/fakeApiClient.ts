import type { ActivityWirePayload, ApiClient, ApiResponse } from "../src/types.ts";

interface StoredRow {
  id: string;
  duration_minutes: number;
  rpe: number;
  performed_at: string;
  server_version: number;
}

/**
 * In-memory stand-in for the real FastAPI endpoint, faithful to its
 * idempotency contract (design.md Decision 3): same client_mutation_id +
 * same payload -> 200 existing row; same key + different payload -> 409.
 * Lets tests inject per-call latency and scripted failures without a real
 * network or server process.
 */
export class FakeApiClient implements ApiClient {
  private readonly rowsByMutationId = new Map<string, StoredRow>();
  private nextServerId = 1;
  public callCount = 0;

  private readonly latencyMs: number;
  private readonly failFirstAttemptFor: Set<string>;
  private readonly terminalFailureFor: Set<string>;
  private readonly conflictFor: Set<string>;
  private readonly attemptCounts = new Map<string, number>();

  constructor(
    latencyMs: number = 0,
    failFirstAttemptFor: Set<string> = new Set(),
    terminalFailureFor: Set<string> = new Set(),
    conflictFor: Set<string> = new Set()
  ) {
    this.latencyMs = latencyMs;
    this.failFirstAttemptFor = failFirstAttemptFor;
    this.terminalFailureFor = terminalFailureFor;
    this.conflictFor = conflictFor;
  }

  async createActivity(payload: ActivityWirePayload): Promise<ApiResponse> {
    this.callCount += 1;
    if (this.latencyMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
    }

    if (this.terminalFailureFor.has(payload.client_mutation_id)) {
      return { status: 422, body: { error: "SIMULATED_TERMINAL_FAILURE" } };
    }

    // Simulates a 409 idempotency conflict, as if the same client_mutation_id
    // had somehow already been used with a different payload server-side.
    if (this.conflictFor.has(payload.client_mutation_id)) {
      return {
        status: 409,
        body: { error: "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD" },
      };
    }

    const attempts = (this.attemptCounts.get(payload.client_mutation_id) ?? 0) + 1;
    this.attemptCounts.set(payload.client_mutation_id, attempts);
    if (attempts === 1 && this.failFirstAttemptFor.has(payload.client_mutation_id)) {
      return { status: 503, body: { error: "SIMULATED_TRANSIENT_FAILURE" } };
    }

    const existing = this.rowsByMutationId.get(payload.client_mutation_id);
    if (existing) {
      const samePayload =
        existing.duration_minutes === payload.duration_minutes &&
        existing.rpe === payload.rpe &&
        existing.performed_at === payload.performed_at;
      if (samePayload) {
        return { status: 200, body: existing as unknown as Record<string, unknown> };
      }
      return {
        status: 409,
        body: { error: "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD", existing_id: existing.id },
      };
    }

    const row: StoredRow = {
      id: `server-${this.nextServerId++}`,
      duration_minutes: payload.duration_minutes,
      rpe: payload.rpe,
      performed_at: payload.performed_at,
      server_version: 1,
    };
    this.rowsByMutationId.set(payload.client_mutation_id, row);
    return { status: 201, body: row as unknown as Record<string, unknown> };
  }

  distinctServerIdCount(): number {
    return new Set([...this.rowsByMutationId.values()].map((r) => r.id)).size;
  }
}

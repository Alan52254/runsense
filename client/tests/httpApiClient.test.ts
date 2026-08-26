import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { HttpApiClient } from "../src/apiClient.ts";
import type { ActivityWirePayload } from "../src/types.ts";

interface RecordedCall {
  url: string;
  init: RequestInit | undefined;
}

function fakeFetch(response: Response, calls: RecordedCall[]): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return response;
  }) as typeof fetch;
}

const samplePayload: ActivityWirePayload = {
  client_mutation_id: "abc-123",
  duration_minutes: 45,
  rpe: 6,
  performed_at: "2026-08-07T09:15:00Z",
};

describe("HttpApiClient", () => {
  it("POSTs to <baseUrl>/activities with JSON headers and the exact payload", async () => {
    const calls: RecordedCall[] = [];
    const response = new Response(JSON.stringify({ id: "server-1", server_version: 1 }), {
      status: 201,
    });
    const client = new HttpApiClient("https://api.example.com", fakeFetch(response, calls));

    await client.createActivity(samplePayload);

    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://api.example.com/activities");
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(
      (calls[0].init?.headers as Record<string, string>)["Content-Type"],
      "application/json"
    );
    assert.equal(calls[0].init?.body, JSON.stringify(samplePayload));
  });

  it("maps a 201 response's status and parsed JSON body through unchanged", async () => {
    const body = { id: "server-1", server_version: 1 };
    const response = new Response(JSON.stringify(body), { status: 201 });
    const client = new HttpApiClient("https://api.example.com", fakeFetch(response, []));

    const result = await client.createActivity(samplePayload);

    assert.equal(result.status, 201);
    assert.deepEqual(result.body, body);
  });

  it("maps a 409 idempotency-conflict response's status and error body through unchanged", async () => {
    const body = { error: "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD" };
    const response = new Response(JSON.stringify(body), { status: 409 });
    const client = new HttpApiClient("https://api.example.com", fakeFetch(response, []));

    const result = await client.createActivity(samplePayload);

    assert.equal(result.status, 409);
    assert.deepEqual(result.body, body);
  });

  it("returns a null body (not a throw) when the response has no parseable JSON", async () => {
    // Simulates a 502 from a proxy/load balancer that returns an HTML/empty
    // error page instead of the JSON the FastAPI backend would send --
    // res.json() throws in that case, and HttpApiClient must not propagate
    // that as an uncaught rejection.
    const response = new Response("<html>Bad Gateway</html>", { status: 502 });
    const client = new HttpApiClient("https://api.example.com", fakeFetch(response, []));

    const result = await client.createActivity(samplePayload);

    assert.equal(result.status, 502);
    assert.equal(result.body, null);
  });

  it("propagates a network-level fetch rejection to the caller", async () => {
    const throwingFetch = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    const client = new HttpApiClient("https://api.example.com", throwingFetch);

    await assert.rejects(() => client.createActivity(samplePayload), TypeError);
  });
});

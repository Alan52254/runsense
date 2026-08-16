# RunSense backend

Implements the `manual-workout-entry` capability: `POST /activities`,
`completed_activities` (PostgreSQL, RLS-enforced), session-RPE calculation.
See `openspec/changes/manual-workout-create-sync/` for the governing spec,
design, and tasks.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

## Running tests

Tests that don't need a database (Pydantic validation, fingerprint
canonicalization, provider seams) run immediately:

```bash
pytest
```

Tests that exercise the real endpoint against Postgres (RLS, idempotency,
timezone derivation) need a reachable database with migrations applied:

```bash
docker compose up -d
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/runsense
alembic upgrade head
export TEST_DATABASE_URL=$DATABASE_URL
pytest
```

Without `TEST_DATABASE_URL`/`DATABASE_URL` reachable, the DB-dependent
tests skip with an explanatory reason rather than failing.

## Running the app

```bash
export DATABASE_URL=postgresql+psycopg://runsense_runtime@localhost:5432/runsense
uvicorn app.main:app --reload
```

The app will refuse to authorize any request until real
`CurrentActorProvider` / `ProfileTimezoneProvider` implementations are
wired in (see `app/providers.py` and design.md Decision 10) -- this is
intentional, not a bug: it's the Auth/Profile changes' job to supply
those, not this one's.

## Competition demo identity (non-production only)

The demo login and database-backed identity providers exist only when the
explicit environment gate is enabled. Set a strong, non-default JWT secret;
startup intentionally fails if the flag is enabled without it:

```bash
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/runsense
export COMPETITION_DEMO_ONLY=true
export DEMO_JWT_SECRET='replace-with-a-long-random-demo-secret'
alembic upgrade head
python scripts/seed_demo_personas.py
uvicorn app.main:app --reload
```

The seed command creates these competition-only credentials:

- `runner.taipei@runsense.demo` / `TaipeiDemo!2026`
- `runner.tokyo@runsense.demo` / `TokyoDemo!2026`
- `runner.london@runsense.demo` / `LondonDemo!2026`

With the flag absent or false, `/auth/demo-login` is not registered and the
original fail-loudly production provider defaults remain active. This demo
mechanism has no refresh rotation, rate limiting, revocation, or lockout.

## Completed activity history

An authenticated athlete can read their own canonical completed activities:

```http
GET /activities?limit=20
Authorization: Bearer <access_token>
```

The `limit` defaults to 20 and must be between 1 and 100. Results are ordered
by performed time, newest first, with a deterministic id tie-breaker:

```json
{
  "items": [
    {
      "id": "...",
      "athlete_id": "...",
      "client_mutation_id": "...",
      "provider": "manual",
      "provider_activity_id": null,
      "duration_minutes": 45,
      "rpe": 6,
      "performed_at": "2026-08-07T09:15:00Z",
      "timezone_snapshot": "Asia/Taipei",
      "local_training_date": "2026-08-07",
      "session_load": 270,
      "unit": "AU",
      "source_metric": "SESSION_RPE",
      "server_version": 1,
      "created_at": "..."
    }
  ],
  "next_cursor": "opaque-value-or-null"
}
```

When `next_cursor` is not null, pass it back unchanged:

```http
GET /activities?limit=20&cursor=<next_cursor>
Authorization: Bearer <access_token>
```

The cursor is opaque and versioned. Clients must never decode, edit, or derive
authorization from it. A malformed or unsupported cursor receives the standard
422 validation response.

### Server/client history contract

- The backend owns the FastAPI/PostgreSQL interface, actor derivation, RLS,
  ordering, pagination cursor, and canonical activity fields.
- The client consumes only `items` and `next_cursor`, returns the cursor
  unchanged for the next page, and does not derive actor identity,
  `session_load`, `timezone_snapshot`, or `local_training_date`.
- The client must treat every activity field as server-returned canonical state
  and must not depend on the cursor's encoded representation.

For a competition demo, log in with one of the personas above, use the returned
`access_token` as the bearer token, create several activities with
`POST /activities`, then traverse them with `GET /activities`.

## Rest days and Training Load Trend

Rest is an explicit Athlete action. Missing activities or device silence never
confirm rest. Set or revoke the desired state with the authenticated interface:

```http
PUT /rest-days/2026-08-08
Authorization: Bearer <access_token>
Content-Type: application/json

{"confirmed":true}
```

The response is `{"date":"2026-08-08","confirmed":true}`. Repeating the same
desired state is idempotent. `confirmed:false` revokes it. Confirming a date that
already has a Completed Activity returns `409` with
`{"error":"REST_DAY_CONFLICTS_WITH_ACTIVITY"}`. Creating an activity on a
previously confirmed date atomically removes the rest confirmation.

Read the 28-day trend ending on an explicit Local Training Date:

```http
GET /training-load/trend?end_date=2026-08-28
Authorization: Bearer <access_token>
```

Omitting `end_date` uses the current calendar date in the authenticated
Athlete's profile timezone. The frozen response shape is:

```json
{
  "start_date": "2026-08-01",
  "end_date": "2026-08-28",
  "series": [
    {
      "unit": "AU",
      "source_metric": "SESSION_RPE",
      "points": [
        {
          "date": "2026-08-01",
          "session_load": 270.0,
          "acute_load": 270.0,
          "chronic_load": 67.5,
          "load_ratio": null,
          "data_quality": "INSUFFICIENT",
          "observation_days": 1,
          "algorithm_version": "tl-v1",
          "schema_version": 1,
          "computed_at": "2026-08-16T00:00:00Z",
          "input_snapshot_hash": "<64 lowercase hex characters>"
        }
      ]
    }
  ]
}
```

Every series contains exactly 28 ascending daily points. AU is always present.
Other units such as `garmin_epoc` are returned as separate series and are never
added to, averaged with, or converted into AU. `SUFFICIENT`, `LOW`, and
`INSUFFICIENT` describe data fitness only: fewer than 21 observation days or
zero chronic load is `INSUFFICIENT` with a null ratio; otherwise mixed units are
`LOW`; a sufficient single-unit window is `SUFFICIENT`. None of these labels is
an alert or Athlete-risk classification.

Run the explicit, repeatable projection backfill after migration and before
enabling the trend UI for an existing database. `DATABASE_URL` must use a
controlled admin role with `SUPERUSER` or `BYPASSRLS`; the command fails loudly
for the normal runtime role so forced RLS cannot produce a false zero-row
success:

```bash
python -m scripts.backfill_training_load
```

### Server/client trend contract

- The backend owns canonical activity/rest facts, Athlete-local date derivation,
  calculations, materialization, unit separation, quality, versions, hashes,
  authentication, and RLS.
- The client sends only `{confirmed}` to the frozen rest endpoint and renders
  each server-returned unit series and neutral quality label from the frozen
  trend response.
- The client never infers rest from silence, recomputes load or ratios, combines
  unlike units, supplies an Athlete identity, or derives colors, thresholds,
  warnings, risk, or alert meaning from the returned values.

Demo flow: log in, create a manual activity, confirm a different date as rest,
then fetch the trend with an explicit `end_date`. The new activity and rest
state are visible in the returned materialized series before each write
response completes.

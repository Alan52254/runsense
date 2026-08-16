# RunSense backend

Implements the `manual-workout-entry` capability: `POST /activities`,
`completed_activities` (PostgreSQL, RLS-enforced), session-RPE calculation.
The server derives actor identity, timezone, local training date, and session
load; clients cannot override those fields.

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

## Profile, Weather, and Training Guidance

These features use three optional environment variables:

```bash
export OPENWEATHER_API_KEY='...'          # optional -- absent means GET /weather
                                           # always returns UNAVAILABLE, not a
                                           # startup failure (weather isn't
                                           # safety-critical like the demo secret)
export OLLAMA_BASE_URL='http://localhost:11434'   # default shown
export OLLAMA_MODEL='llama3.2:3b'                 # default shown
```

**Demo-day checklist for the tone layer:** `ollama pull llama3.2:3b` once,
then `ollama serve` before judging starts. If Ollama isn't running,
`GET /guidance/today` still returns 200 with the deterministic recommendation
and the fixed `NEUTRAL_FALLBACK` tone -- this fallback path is exercised by
`backend/tests/test_llm_client.py` and is not a degraded/error state from the
client's point of view.

```http
PATCH /profile
Authorization: Bearer <access_token>
Content-Type: application/json

{"city":"Taipei"}
```

Both `city` and `timezone` are optional and independent; at least one must be
present (`422 EMPTY_PROFILE_UPDATE` otherwise). Response:
`{"city":"Taipei","timezone":"Asia/Taipei"}`.

```http
GET /weather
Authorization: Bearer <access_token>
```

Uses the city from the athlete's profile -- never live device geolocation
(REQ-WEATHER-LOCATION-001). Response is always one of four states:

```json
{
  "state": "LIVE",
  "city": "Taipei",
  "temperature_c": 30.4,
  "humidity_pct": 70.0,
  "observed_at": "2026-08-17T02:00:00Z",
  "pace_adjustment_sec_per_km": 46
}
```

`LIVE` (fresh provider call), `CACHED` (a call within the last 10 minutes,
provider not re-called), `STALE` (provider call failed, serving a cached
value up to 3 hours old), or `UNAVAILABLE` (no city set, or the provider
failed with nothing usable cached) -- in the last two cases every numeric
field is `null`, never a stale value presented as current.

```http
GET /guidance/today?llm_tone_enabled=true
Authorization: Bearer <access_token>
```

```json
{
  "local_date": "2026-08-17",
  "recommendation": {
    "workout_type": "輕鬆有氧跑",
    "duration_minutes": 30,
    "distance_km": null,
    "target_pace_sec_per_km": null,
    "intensity_label": "RPE 3-4",
    "adjustment_reason_code": "INSUFFICIENT_DATA",
    "algorithm_version": "guidance-rule-2026.08.1"
  },
  "tone_variant_id": "NEUTRAL_FALLBACK",
  "tone_text": "以下是今天的課表。",
  "tone_reviewed_by": "系統預設",
  "computed_at": "2026-08-17T02:00:05Z"
}
```

Computed at most once per athlete per local calendar date (REQ-AI-COST-001);
later requests on the same date return the cached result. `recommendation`
is entirely deterministic -- see `app/recommendation_engine.py`'s rule table
over the athlete's own `load_ratio`/`data_quality` -- and has no LLM
involvement at any point (REQ-AI-004). The LLM's only authority is picking
`tone_variant_id` from a five-value whitelist (REQ-AI-006); any response
outside that exact shape is discarded wholesale and falls back to
`NEUTRAL_FALLBACK` (REQ-AI-007). Pass `llm_tone_enabled=false` to skip the
LLM call entirely (REQ-PRIV-004) -- the recommendation is unaffected either
way.

### Server/client guidance contract

- The backend owns city resolution, the weather cache/fallback state
  machine, the deterministic recommendation rule table, the LLM call and its
  strict schema validation, the tone template lookup, and the once-per-day
  cache.
- The client sends only `{city?, timezone?}` to `PATCH /profile` and
  `llm_tone_enabled` to `GET /guidance/today`, and renders the four weather
  states and the recommendation/tone fields as returned -- it never computes
  a pace adjustment, a recommendation, or a tone selection itself.
- Neither the pace-adjustment formula (`app/weather_pace.py`) nor the
  recommendation rule table (`app/recommendation_engine.py`) is specified by
  the SRS/test spec -- both are documented, isolated, swappable defaults
  (see design.md Decisions 3 and 5), not a scientific or training-science
  claim.

Demo flow: set a profile city, fetch weather (works even without a real
OpenWeatherMap key -- shows `UNAVAILABLE` cleanly), fetch today's guidance
(works even without Ollama running -- shows the deterministic recommendation
with a neutral tone), then start Ollama and fetch again to see a real
selected tone.

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

# PowerShell database setup
$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/runsense"
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
createdb -h localhost -U postgres runsense_test
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/runsense_test
DATABASE_URL=$TEST_DATABASE_URL alembic upgrade head
pytest
```

`TEST_DATABASE_URL` must name a database separate from `DATABASE_URL` because
the integration-test fixtures truncate every application table. The test
suite refuses to run when both variables identify the same host, port, and
database. Without a reachable `TEST_DATABASE_URL`, DB-dependent tests skip
with an explanatory reason rather than risking runtime/demo data.

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
export OLLAMA_MODEL='llama3.2:3b'                 # tone selection only (default shown)
export GUIDANCE_PROVIDER='groq,ollama'            # health coach: Groq, then the local model
export OLLAMA_COACH_MODEL='qwen2.5:7b'            # the health coach's local model (default shown)
```

**Demo-day checklist for the health coach:** `ollama pull qwen2.5:7b` once and keep
`ollama serve` running. With `GUIDANCE_PROVIDER=groq,ollama` the coach answers from
Groq and moves to the local model when Groq is out of quota or unreachable
(`backend/tests/test_coach_provider_chain.py`); the backend loads the local model
in the background at startup so that fallback does not wait ~1 minute. If no
provider answers, the coach says so plainly rather than inventing a reply.

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

## Coach Team Overview + Coach Athlete Detail

Implements docs/mvp-checklist.md Backlog Item 1. See CONTEXT.md for Team /
Team Role / Team Membership / Coach Roster Row / Consent Scope. A Coach
Roster Row is a query-time projection, never a stored copy: a field is
populated only when the athlete's currently granted Consent Scopes cover it.

```http
GET /teams/mine
Authorization: Bearer <access_token>
```

Lists the Teams the authenticated actor holds a coach-ish Team Role
(`coach`/`head_coach`/`owner`) in. This endpoint is not literally one of
Item 1's two listed endpoints -- it was added because the web coach screens
need a `team_id` to call the roster/detail endpoints below with at all, and
there is no other endpoint that discovers one yet.

```json
{"items": [{"team_id": "...", "name": "臺北長跑訓練隊", "role": "head_coach"}]}
```

```http
GET /teams/{team_id}/roster
Authorization: Bearer <access_token>
```

Returns every `ACTIVE` `athlete`-role Team Membership in the team, each
projected into a Coach Roster Row. A caller who does not hold an `ACTIVE`
coach-ish Team Role for `team_id` gets the same generic `403
NOT_AUTHORIZED` whether the team exists or not (no membership-existence
leak, matching the rest of this app's auth error posture). A departed
(`LEFT`) or still-`INVITED` athlete's row is absent from `items` entirely --
not present-but-masked.

```json
{
  "team_id": "...",
  "items": [
    {
      "team_id": "...",
      "athlete_id": "...",
      "name": "Tokyo runner",
      "status": "ACTIVE",
      "joined_at": "...",
      "granted_scopes": ["activity_summary", "training_load", "injury_status"],
      "last_activity_local_date": "2026-08-23",
      "acute_load_au": 320.0,
      "chronic_load_au": 210.5,
      "load_ratio": 1.52,
      "data_quality": "SUFFICIENT",
      "last_14_days_load": [0, 320, 0, ...],
      "injury_has_issue": null,
      "injury_severity_band": null,
      "injury_free_text": null
    }
  ]
}
```

`last_activity_local_date` is null unless `activity_summary` is granted;
`acute_load_au`/`chronic_load_au`/`load_ratio`/`data_quality`/
`last_14_days_load` are null/empty unless `training_load` is granted.
`data_quality` uses the same `SUFFICIENT`/`LOW`/`INSUFFICIENT` vocabulary as
`GET /training-load/trend`. Injury summary and free text are projected
independently under `injury_status` and `injury_detail` consent.

```http
GET /teams/{team_id}/athletes/{athlete_id}
Authorization: Bearer <access_token>
```

The same projection for one athlete (`AthleteDetailScreen`). `404
TEAM_ATHLETE_NOT_FOUND` covers both "never was a member of this team" and
"membership is `LEFT`" identically -- same non-leak posture as the roster's
403. Requires the same coach-ish Team Role as the roster endpoint.

### RLS shape

`teams`, `team_memberships`, and `consent_grants` (migration `0010`) are
`ENABLE`+`FORCE` row-level security, like every other RLS table in this app.
Unlike the athlete-owned tables (`completed_activities`,
`training_load_daily`, ...), which stay `athlete_id = actor`-only, these
three use `SECURITY DEFINER` membership predicates with a fixed
`search_path`. This avoids recursive policy evaluation while letting a
coach read only rows belonging to an actively coached team. Function access
is revoked from `PUBLIC` and granted only to `runsense_runtime`.

`completed_activities` and `training_load_daily` add SELECT-only coach
policies backed by `app_actor_can_read_athlete`. The roster/detail routes
keep the verified coach as `app.actor_user_id` for the full transaction;
target athlete ids remain query parameters and are never installed as the
actor context. Each protected read therefore rechecks active shared Team
Membership and the required current Consent Scope inside PostgreSQL.

### Athlete membership and consent

`GET /me/team-memberships` and membership PATCH actions expose the athlete's
own invitations and membership lifecycle. `GET /me/consent-grants` and
`PATCH /me/consent-grants/{scope}` manage each scope independently. Leaving
a team revokes its grants before the membership becomes `LEFT`.

### Demo seeding

`scripts/seed_demo_personas.py` now also seeds one demo Team (`臺北長跑訓練隊`):
the Taipei persona as `head_coach`, the Tokyo and London personas as
`athlete` members with different granted Consent Scopes, eight sample
Completed Activities per athlete, and body-status examples -- materialized into real
`training_load_daily` rows via the same `recompute_training_load` path
`POST /activities` uses, not hand-inserted numbers. Re-running the script is
idempotent, same as the rest of it.

## Settings -- Security/Privacy/Integration

Implements the Settings item pulled back into scope from
docs/mvp-checklist.md's former "Deferred past MVP" section
(`REQ-AUTH-007/008`, `REQ-PRIV-001…006`, the Garmin flag, `REQ-AUDIT-001/002`).
Deliberately demo-appropriate, not full compliance infrastructure --
`app/routes/settings.py`, prefix `/me/settings` (distinct from `app/routes/me.py`'s
bare `/me/...` prefix).

- `GET /me/settings/sessions` -- the actor's own `auth_sessions` rows
  (device, masked IP, location, last-active, `is_current`). A row is
  written at every `POST /auth/demo-login` (see `app/routes/demo_auth.py`),
  which also mints a `sid` claim into the JWT so later requests can tell
  which session issued them.
- `DELETE /me/settings/sessions/{session_id}` -- marks a session revoked.
  Revoking the current session is allowed; nothing special-cases it.
- `POST /me/settings/mfa/verify` -- accepts the fixed demo code `424242`
  (matching web/README.md's documented step-up code) and sets
  `auth_sessions.mfa_satisfied = true` for the caller's current session.
  This is a lightweight MFA-satisfied toggle to demonstrate REQ-AUTH-007's
  gate, **not** a real TOTP/SMS integration.
- `GET /me/settings/privacy/export` -- a JSON dump of the athlete's own
  `athlete_profiles`, `completed_activities`, and `training_load_daily`
  rows, reusing `activities.py`/`training_load.py`'s existing query
  patterns rather than a parallel export path. Also writes a `DATA_EXPORT`
  audit_log entry.
- `POST /me/settings/privacy/deletion-request` -- sets
  `users.deletion_requested_at`. Does **not** delete anything or schedule a
  job -- REQ-PRIV-003/005's actual retention-period deletion pipeline is
  out of scope for this MVP; this only records that the request happened
  so the UI can show an honest "deletion requested" state.
- `GET /me/settings/integrations/garmin` -- reads `GARMIN_ACTIVITY_SYNC_ENABLED`
  (default off) and returns `{"enabled": false, "reason": "GARMIN_ACTIVITY_SYNC_ENABLED
  is off (Phase 1A)"}` when unset, directly reflecting REQ-GARMIN-001. No
  real Garmin OAuth.
- `GET /me/settings/audit-log` -- the actor's own `audit_log` rows, newest
  first. `event` is constrained to the exact 8-value enum already in
  `web/src/lib/types.ts` `AuditEvent`; `summary` is always a short
  server-constructed string (never a password, token, injury free text, or
  raw payload -- enforced by construction, since every insert site passes a
  literal string, not caller input). This change only emits `AUTH_LOGIN`
  (at login) and `DATA_EXPORT` (at export) -- `CONSENT_GRANT`/`CONSENT_REVOKE`
  are defined but intentionally left unpopulated here; they're Item 2's
  backend's job to emit once it exists.

`auth_sessions`/`audit_log` are `ENABLE`+`FORCE` RLS, self-only (matching
the `athlete_id = actor`-only pattern from migration `0005`, not the
coach-widened pattern from `0010`) -- nobody, coach or otherwise, reads
another user's sessions or audit trail through this surface.

## Coach Assignments (AssignedWorkout)

Implements the Assignments item pulled back into scope from
docs/mvp-checklist.md's former "Deferred past MVP" section. See
CONTEXT.md's Assigned Workout definition. `app/routes/assignments.py`.

```http
POST /teams/{team_id}/assignments
Authorization: Bearer <coach access_token>
Content-Type: application/json

{"athlete_id":"...","local_date":"2026-08-24","title":"輕鬆有氧跑","duration_minutes":30,"intensity_label":"RPE 3-4"}
```

Requires the actor to hold a coach-ish Team Role (`coach`/`head_coach`/`owner`)
on `team_id` (same `_require_coach_role` shape as `app/routes/teams.py`,
generic `403 NOT_AUTHORIZED` for both "not a coach" and "team doesn't
exist"), and the target `athlete_id` to have an `ACTIVE` `athlete` Team
Membership on that same team -- `404 ASSIGNMENT_ATHLETE_NOT_ELIGIBLE`
otherwise (covers "never a member" and "LEFT" identically, matching
`TeamAthleteNotFoundError`'s non-leak posture). New rows start
`status: "SCHEDULED"`.

```http
GET /teams/{team_id}/assignments
Authorization: Bearer <coach access_token>
```

Every assignment for that team, newest-date-first. Same coach-role
requirement as the `POST` above. No filtering/pagination for MVP -- a flat
list is what `AssignmentsScreen.tsx` actually needs.

```http
GET /me/assigned-workouts
Authorization: Bearer <access_token>
```

The athlete's own assignments across every team they belong to. **Path
naming decision**: the obvious `/me/assignments` would read as if it
belonged next to the membership and consent resources in `app/routes/me.py`
(team-memberships, consent-grants) -- it doesn't, it lives in this
change's `assignments.py`. `/me/assigned-workouts` names the exact
CONTEXT.md term instead of the generic word "assignments", which also
also prevents future `/me` resources from becoming ambiguous.

No `PATCH` (mark `COMPLETED`/`MISSED`) for MVP -- `AssignmentsScreen.tsx`
only lists and creates; there is no such interaction to wire yet.

`assigned_workouts` RLS: `SELECT` USING (`athlete_id = actor` OR
`app_actor_is_active_team_coach(team_id)`, reusing migration `0010`'s
helper function rather than a parallel one); `INSERT` `WITH CHECK` requires
both the actor to be an active team coach *and* an `EXISTS` proving the
target athlete's `ACTIVE` membership -- the same defense-in-depth shape as
`consent_grants_athlete_write` in migration `0010`.

## Health coach and training-plan intelligence

- `POST /injury-guidance` applies fixed red-flag triage first, retrieves only
  reviewed evidence from the versioned evidence graph, then optionally asks
  Groq or Gemini to restate that bounded result. Provider failure or a missing
  key falls back to deterministic guidance. Set `GUIDANCE_PROVIDER` to
  `static`, `groq`, or `gemini`; keys remain server-side only.
- `GET /training-plan/today` reads the authenticated athlete's AU training
  load, profile-city weather, and latest injury severity. It returns bounded
  candidates plus ranker version, feature coverage, and explicit abstention.
  The production default is deterministic; offline learned rankers must not be
  enabled without locked evaluation evidence.

Neither endpoint diagnoses an injury or clears an athlete to run. Injury free
text and Garmin records are not sent to hosted language-model providers.

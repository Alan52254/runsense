# RunSense — MVP Checklist

Scope and decisions locked in a grilling session on 2026-08-24. See [CONTEXT.md](../CONTEXT.md) for terms
used below (Team, Team Role, Team Membership, Coach Roster Row, Injury Report, Consent Scope, Assigned Workout).

## Confirmed decisions

- **Platform**: web only (`web/`). Mobile (`mobile/`) is deferred — it will later clone the finished web
  layout, not be built in parallel.
- **Auth**: keep `COMPETITION_DEMO_ONLY` demo-JWT / seeded personas. Real auth
  (`auth-profile-foundation`) stays out of MVP.
- **Hosting**: local-only. The MVP demo is a recorded video, not a live deployment.
- **Weather**: OpenWeatherMap key obtained, in `backend/.env` (gitignored). Already wired in code.
- **LLM**: local Ollama (`llama3.2:3b`), unchanged — no hosted LLM API needed.
- **Access rule**: a Team Membership of `LEFT` removes the athlete's Coach Roster Row entirely (query-time
  projection off current Consent Scopes — no historical/read-only visibility for MVP).

## Backlog, in build order

The three MVP slices below are implemented. Keep this list as the handoff record and use the deferred
section as the boundary for follow-up work.

### 1. Coach Team Overview + Coach Athlete Detail (core coach loop)

- [x] Data model: `teams`, `team_memberships` (role, status, joined/left timestamps), RLS scoped to team
      membership. Also added a minimal `consent_grants` table (see backend/README.md) — just enough to gate
      Coach Roster Row field visibility; full consent-grant CRUD is still Item 2's job.
- [x] Endpoint: `GET /teams/{team_id}/roster` → list of Coach Roster Row projections (per athlete: name,
      status, granted scopes, acute/chronic load, load ratio, data quality, last activity date, last-14-day
      load series, injury summary — only fields covered by that athlete's currently granted Consent Scopes).
      Injury summary and detail are independently projected from the split injury-report storage.
- [x] Endpoint: `GET /teams/{team_id}/athletes/{athlete_id}` → single Coach Roster Row detail (same
      projection, single-athlete view for `AthleteDetailScreen`).
- [x] Enforce: `LEFT` membership → row excluded from roster and detail queries (not soft-deleted, just
      absent). Covered by `backend/tests/test_teams_roster.py`.
- [x] Wire `screens/coach/TeamOverviewScreen.tsx` off `demoData.ts` → real roster endpoint.
- [x] Wire `screens/coach/AthleteDetailScreen.tsx` off `demoData.ts` → real detail endpoint (reuses the
      same live roster the workspace already fetched — see backend/README.md's traceability note).
- Also added `GET /teams/mine` (not in the original list above): the coach screens need a `team_id` to call
  the two endpoints above with at all, and there was no other way to discover one. Minimal plumbing, not
  Item 2/3 material — see backend/README.md.
- Code-reviewed and fixed: a real (non-demo) coach with zero coached teams no longer sees the seeded demo
  team's name on `TeamOverviewScreen`; `get_team_athlete`'s consent lookup now filters in SQL instead of
  Python.
- Coach reads keep the coach as the database actor. RLS policies authorize the current team relationship and
  consent at query time; routes never impersonate the target athlete.
- Verified against PostgreSQL with migrations through `0012`: the complete backend suite passes (181 tests).

### 2. Athlete Team / Consent screen

- [x] Endpoint: `GET /me/team-memberships` plus accept/decline/leave actions for the athlete's own membership.
- [x] Endpoint: `GET /me/consent-grants` / `PATCH /me/consent-grants/{scope}` → grant/revoke one
      `ConsentScope` (`activity_summary`, `training_load`, `injury_status`, `injury_detail`) per team,
      independently.
- [x] Revoking a scope is reflected on the *next* Coach Roster Row query — no caching that would show
      stale granted data to a coach.
- [x] Wire `screens/athlete/TeamScreen.tsx` to real membership + consent endpoints with loading/error recovery.

### 3. Athlete Body Status

- [x] Data model: `injury_reports` (summary: `hasIssue`, `severityBand`, `bodyPart`, `localDate`) and
      `injury_report_details` (free text) as **separate tables with separate RLS policies** — detail must
      never be joinable without the `injury_detail` Consent Scope specifically.
- [x] Endpoint: `POST /injury-reports`, `GET /injury-reports` (self), matching the existing
      manual-workout-entry idempotency/ownership pattern already used for activities.
- [x] Wire `screens/athlete/BodyStatusScreen.tsx` to real endpoints with idempotent submission.

### 4. Settings — Security/Privacy/Integration

Pulled back into scope from the former "Deferred past MVP" entry below. Deliberately demo-appropriate, not
full compliance infrastructure — see backend/README.md's Settings section for exactly what each endpoint
does and does not do.

- [x] Data model: `auth_sessions` (device, masked IP, location, last-active, `mfa_satisfied` per session),
      `audit_log` (actor, 8-value event enum matching `web/src/lib/types.ts` `AuditEvent`, short
      server-constructed summary), and `users.deletion_requested_at`.
- [x] Endpoint: `GET /me/settings/sessions`, `DELETE /me/settings/sessions/{session_id}` — list/revoke the
      actor's own sessions. A row is written at every `POST /auth/demo-login`, which also mints a `sid`
      JWT claim so later requests know which session issued them.
- [x] Endpoint: `POST /me/settings/mfa/verify` — a lightweight MFA-satisfied toggle accepting the fixed demo
      code `424242` (REQ-AUTH-007's gate demonstration, not a real TOTP/SMS integration).
- [x] Endpoint: `GET /me/settings/privacy/export` — JSON dump of the athlete's own profile, completed
      activities, and training load, reusing `activities.py`/`training_load.py`'s existing query patterns.
- [x] Endpoint: `POST /me/settings/privacy/deletion-request` — records `deletion_requested_at` only.
      REQ-PRIV-003/005's actual retention-period deletion pipeline stays out of scope for this MVP.
- [x] Endpoint: `GET /me/settings/integrations/garmin` — reflects `GARMIN_ACTIVITY_SYNC_ENABLED`
      (REQ-GARMIN-001), default off, no real Garmin OAuth.
- [x] Endpoint: `GET /me/settings/audit-log` — the actor's own entries. Login, data export, and consent
      grant/revoke events are constructed by the server and recorded for the authenticated actor.
- [x] Wire `screens/athlete/settings/{SecuritySettings,PrivacySettings,IntegrationSettings}.tsx` to the real
      endpoints via `WorkspaceContext` (sessions, audit log, export, deletion-request, the Garmin flag) —
      the existing demo-fallback pattern needed no changes to the screen components themselves.
- **Known tradeoff, not fixed**: REQ-PRIV-004 (LLM-tone opt-out) and REQ-PRIV-006 (policy-version display)
  stay client-side/demo-only — no backend endpoint exists for either, and neither was in this item's
  brief. `PrivacySettings`'s "correct personal data" affordance also stays a pointer to the existing
  profile screen, not a new endpoint.
- **Verification gap**: none — the full backend suite (181 tests) has
  run against real PostgreSQL with migrations through `0012`. See the "Verification" note under Item 5.

### 5. Coach Assignments (`AssignedWorkout`)

Pulled back into scope from the former "Deferred past MVP" entry below. See CONTEXT.md's Assigned Workout
definition.

- [x] Data model: `assigned_workouts` (team, athlete, date, title, duration, intensity, status
      `SCHEDULED`/`COMPLETED`/`MISSED`), matching `AssignedWorkout` in `web/src/lib/types.ts` exactly.
- [x] Endpoint: `POST /teams/{team_id}/assignments` — coach creates an assignment for one of their team's
      `ACTIVE` athletes; verifies coach-ish Team Role and target athlete eligibility, rejecting otherwise
      (`403`/`404`, matching `app/routes/teams.py`'s existing non-leak error posture).
- [x] Endpoint: `GET /teams/{team_id}/assignments` — coach lists their team's assignments (flat list, no
      filtering — that's what `AssignmentsScreen.tsx` needs).
- [x] Endpoint: `GET /me/assigned-workouts` — athlete's own view across every team. Path-naming decision
      (not `/me/assignments`, to keep the Assigned Workout resource name explicit) is
      documented in backend/README.md.
- [x] No `PATCH` for MVP — `AssignmentsScreen.tsx` only lists and creates.
- [x] Wire `screens/coach/AssignmentsScreen.tsx` to the real list/create endpoints (a "新增指派" modal
      replaces the previously-disabled button when a backend and a coached team are both present).
- **Known tradeoff, not fixed**: `GET /me/assigned-workouts` has no dedicated athlete-facing screen yet — it
  is fetched into `WorkspaceContext.myAssignedWorkouts` but nothing renders it, since no athlete screen
  asked for it in this item's brief.
- **Verification**: migration `0012` applied cleanly against real PostgreSQL; the full backend suite passes
  (181 tests total, including session revocation, MFA gating, consent-audit, injury-projection, Settings,
  Assignments, and CORS regressions). `npm run build`
  (`tsc -b && vite build`) and `npm run lint` (oxlint) both pass clean on `web/`.

### Deferred past MVP (do not build yet)

- [ ] Mobile app: clones the web layout once web is done. Not started until web MVP + design pass are
      complete.
- [ ] Real auth (`auth-profile-foundation`): signup/login/session model. Demo auth stays for MVP.

## Parallel track: design/UX polish

- [x] Replace generic/AI-coded iconography with a coherent running, recovery, coaching, and privacy icon set.
- [x] Establish an endurance palette, responsive cards, compact mobile metrics, safe-area bottom navigation,
      a bottom-sheet overflow menu, meaningful motion, and reduced-motion support.
- [x] Remove development-stage labels and internal API wording from the primary user experience.
- [x] Keep all athlete features reachable on mobile, including body status, team consent, and settings.
- [x] Remove template-feeling flourishes that don't carry information: decorative radial-gradient "ambient
      glow" blobs behind the whole app shell, a diagonal gradient on every card background, card hover-lift
      on non-clickable cards, a glowing box-shadow under the primary button, a staggered fade-in-rise
      animation on every page navigation, and purely ornamental color dashes on dashboard stat tiles.
      `.card-featured`/`.card-chart` keep a meaningful solid accent-colored top bar (was a fading gradient)
      — tone system and layout untouched, this only removed decoration that didn't map to anything.
      Verified: `npm run build`/`lint` clean, with browser checks at 390 × 844 phone and desktop viewports.

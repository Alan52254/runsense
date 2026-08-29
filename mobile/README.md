# RunSense mobile

Expo (React Native + TypeScript) app. Consumes four backend capabilities
unmodified: `identity-demo-gate` (login), `manual-workout-create-sync`
(log a workout), `activity-history-list` (history), and
`rest-day-training-load-trend` (rest days + trend). See
`openspec/changes/manual-workout-entry-ui/` and
`openspec/changes/mobile-persistent-insights/` for the governing specs.

## Setup

```bash
cd mobile
npm install
```

## Pointing at a local backend

```bash
export EXPO_PUBLIC_API_BASE_URL=http://localhost:8000
npx expo start
```

Defaults to `http://localhost:8000` if unset. On a physical device (not a
simulator), `localhost` won't resolve to your dev machine -- use your
machine's LAN IP instead (e.g. `http://192.168.1.23:8000`).

## Backend must be running with the demo gate enabled

```bash
cd ../backend
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/runsense
export COMPETITION_DEMO_ONLY=true
export DEMO_JWT_SECRET='replace-with-a-long-random-demo-secret'
alembic upgrade head
python scripts/seed_demo_personas.py   # only needed once per database
uvicorn app.main:app --reload
```

## Demo login credentials

Seeded by `backend/scripts/seed_demo_personas.py`:

- `runner.taipei@runsense.demo` / `TaipeiDemo!2026`
- `runner.tokyo@runsense.demo` / `TokyoDemo!2026`
- `runner.london@runsense.demo` / `LondonDemo!2026`

## Screens

Assembled by the `expo-demo-parity` OpenSpec change into one athlete
walkthrough. Authenticated navigation is a native-stack whose first screen
is a bottom-tab navigator; `LiveRun` and `LogWorkout` are pushed on top.

- **Login** -- shown only when no session is restored.
- **Today** (tab, `DashboardScreen.tsx`) -- post-login home. Today's
  recommendation (workout type, duration, distance, target pace) from
  `GET /guidance/today`, weather + weather-adjusted pace from `GET /weather`
  (target pace + server `pace_adjustment_sec_per_km` only -- no on-device
  physiology), a training-load HUD from `GET /training-load/trend`, a
  body-status snapshot from `GET /injury-reports`, and quick actions into
  live run / manual log. Each section fetches independently
  (`Promise.allSettled`) so one failure does not blank the screen. The
  deterministic-engine / human-reviewed-tone disclaimer
  (`RECOMMENDATION_DISCLAIMER`) is always visible next to the recommendation;
  the tone message is rendered subordinate with its `tone_reviewed_by`
  attribution. Load values are plain neutral text -- no code path maps any
  value to a color, icon, or band (REQ-METRIC-001).
- **History** (tab) -- paginated list of completed activities. Unchanged.
- **Body** (tab, `BodyScreen.tsx`) -- `POST /injury-reports` form
  (has-issue / severity / body part / private note) with an idempotent
  `client_mutation_id` (a fresh report gets a fresh id; a retry of the same
  one reuses it), self history from `GET /injury-reports`, and rejection vs.
  network states kept distinct. Also hosts the **health-coach channel entry
  point**, rendered from `HealthCoachChannel.getStatus()` -- currently
  `UnavailableHealthCoachChannel` (`NOT_YET_AVAILABLE`), so it shows the
  not-medical-advice disclaimer and a disabled affordance, never a form it
  cannot submit and never a fabricated coach reply.
- **LiveRun** (`LiveRunScreen.tsx`, pushed) -- single-device manual timer,
  no GPS (REQ-SCOPE-001). Distance / pace / heart rate are typed in.
  "Finish" collects an RPE and calls `POST /activities` exactly once with
  the elapsed duration; a failed save keeps the athlete on the summary with
  their data intact and a retry, and history is not shown as if it saved.
- **LogWorkout** (`LogWorkoutScreen.tsx`, pushed, replaces `EntryScreen.tsx`)
  -- manual `duration_minutes` + `rpe` to `POST /activities`; shows the
  server-returned `session_load`, never a value recomputed on-device.
- **Trend** (tab) -- 28-day per-unit Training Load Trend, plus a Rest Day
  confirm/revoke control. Renders `data_quality` as plain neutral text only
  -- there is no code path anywhere in `TrendScreen.tsx`/`RestDayControl.tsx`
  that maps a value to a color, icon, or threshold. That's structural
  (REQ-METRIC-001), not a styling choice to remember. Kept as-is; not part
  of the new demo flow (`origin/main` web no longer exposes rest days).

## Pure modules and tests

`src/format.ts`, `src/healthCoach.ts`, and `src/recommendation.ts` have no
`react-native` import and are covered by `node --test` (21 tests):

```bash
npm test        # node --test src/*.test.ts
npm run typecheck   # tsc --noEmit  &&  tsc --noEmit -p tsconfig.test.json
```

`recommendation.ts` (`buildRecommendationView`) is the only place the app
turns guidance + weather into displayed numbers; the dashboard renders its
output and does no arithmetic inline.

## Session persistence

The access token is stored in `expo-secure-store` (OS Keychain/Keystore --
see `src/session.ts`), not `AsyncStorage`, satisfying REQ-AUTH-006's mobile
clause. `src/SessionContext.tsx` owns the whole session lifecycle behind a
small interface (`status`, `login`, `logout`, `request`):

- On launch, `status` is `"restoring"` while the token is read from secure
  storage -- this is what prevents a login-screen flash before the restore
  finishes.
- `request(fn)` is how every authenticated screen calls the API: it resolves
  the current token, calls `fn(token)`, and if the response is a 401/403 it
  logs out automatically before rethrowing. Screens never check for auth
  failures themselves.
- Logout clears secure storage; a relaunch afterward shows Login, not a
  residual session.

This is still the same demo access token `identity-demo-gate` issues -- no
refresh rotation, no revocation list, no rate limiting. Persisting it
securely doesn't change what it is, only where it lives on-device.

## What's verified vs. not

**Verified in this change (`expo-demo-parity`):**

- `npm test` -- 21 `node --test` cases green (`format`, `healthCoach`,
  `recommendation`), including every weather-adjusted-pace null path and the
  "never a band word" check on the ratio label.
- `npm run typecheck` -- `tsc --noEmit` clean on app code and on the test
  files (`tsconfig.test.json`).
- `npx expo export --platform android` -- bundles 857 modules, no errors.
- `npx expo-doctor` -- 19/21. The two failures pre-date this change and are
  dependency hygiene, not screen defects: (1) `@expo/vector-icons` wants an
  `expo-font` peer -- this change removed the last import of
  `@expo/vector-icons`, so the dependency can simply be dropped; (2) patch
  drift on `expo` / `expo-secure-store` / `react-native`.
- Endpoint request/response shapes: the injury-report functions in
  `src/api.ts` were written against `backend/app/schemas.py`
  (`CreateInjuryReportRequest` / `InjuryReportResponse`); the guidance,
  weather, trend, history and activity shapes are unchanged from the prior
  slices, which verified them by curl against a live seeded backend.

**Not verified:** not run in a simulator or on a device in this session --
no GUI available. Screen rendering, navigation push/tab transitions, the
live-run timer over real elapsed time, pull-to-refresh, and the
force-quit/relaunch session restore are implemented per spec but only
exercised at the type-check / bundle / API-contract level. A device pass is
required before treating this flow as demo-ready.

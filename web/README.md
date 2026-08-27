# RunSense Web

The athlete + coach web UI for RunSense Phase 1A. Vite + React + TypeScript,
no UI framework and no chart library — the design tokens and the SVG charts are
in-repo so both can be traced and changed directly.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build
```

## Two data modes

By default the app runs on the seeded demo dataset in `src/data/demoData.ts`
(34 days of activities, a team, consent grants, sessions, an audit log), so
every screen is walkable without Postgres.

Point it at a running backend to make login, workout creation, activity
history, training load, and the coach team overview / athlete detail
screens hit the real endpoints:

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

`src/data/apiClient.ts` connects authentication, activity creation and history,
training-load trends, profile settings, weather, daily guidance, the coach
roster/athlete-detail projection, team memberships, consent grants, injury
reports, settings (sessions, MFA-satisfied, privacy export/deletion-request,
the Garmin flag, the audit log), and coach assignments to the live backend.

There is no rest-day concept in the frontend: a day with no activity record
is simply a day with no run, shown uniformly (no separate "confirmed rest"
marker or action). The backend's `PUT /rest-days/{date}` endpoint and
`athlete_rest_days` table still exist (see `backend/README.md`) but nothing
in this UI calls them.

One thing worth knowing about how the real data is wired:

- **History** merges the real `GET /activities` fetch with the existing
  offline-first local queue (unsynced/failed writes), deduped by
  `client_mutation_id`, so an in-flight save is never lost or double-shown.
- **Coach roster** (`TeamOverviewScreen`, `AthleteDetailScreen`) comes from
  `GET /teams/mine` + `GET /teams/{team_id}/roster` when a backend is
  configured — `WorkspaceContext`'s `coachRoster` switches to the live
  projection, gated field-by-field by the athlete's actual granted Consent
  Scopes (`src/lib/liveCoachData.ts`). `departedNotice` stays demo-only
  illustrative content either way: the roster query makes a `LEFT`
  membership genuinely absent rather than returning a "recently departed"
  event. `AthleteDetailScreen` reads the same already-fetched roster array
  rather than making a second network call — the single-athlete
  `GET /teams/{team_id}/athletes/{athlete_id}` endpoint exists and is
  tested on the backend, but the workspace already has the row.
- **Coach assignments** (`AssignmentsScreen`) comes from
  `GET /teams/{team_id}/assignments` (list, scoped to the same team
  `liveTeamId` the roster resolved) and `POST /teams/{team_id}/assignments`
  (the "新增指派" modal, enabled only when a backend and a coached team are
  both present). The athlete's own cross-team view,
  `GET /me/assigned-workouts`, is fetched into `WorkspaceContext`'s
  `myAssignedWorkouts` but has no dedicated screen yet — no athlete UI asked
  for it in this change's scope.
- **Settings** (`SecuritySettings`, `PrivacySettings`, `IntegrationSettings`)
  read `sessions`/`auditLog` from `GET /me/settings/sessions` and
  `GET /me/settings/audit-log`; `exportData`/`requestAccountDeletion` call
  `GET /me/settings/privacy/export` and
  `POST /me/settings/privacy/deletion-request` directly rather than
  building a client-side payload; `IntegrationSettings` additionally shows
  the real `GET /me/settings/integrations/garmin` flag state alongside the
  existing demo-only simulation toggle (see "Two demo-only affordances"
  below — those stay separate on purpose). None of this is full compliance
  infrastructure -- see `backend/README.md`'s Settings section for the
  documented scope of each endpoint (e.g. the deletion-request endpoint only
  records a timestamp; no retention-period deletion pipeline runs).

Demo credentials come from `backend/scripts/seed_demo_personas.py`. The MFA and
step-up challenges accept the fixed code `424242` — entering it also calls
the real `POST /me/settings/mfa/verify` in the background when a backend is
configured (best-effort; the UI gate itself stays a synchronous local check
so it never blocks on a network round trip).

## Screens

**Athlete** — 今日總覽 · 記錄訓練 · 訓練紀錄 · 訓練負荷 · 身體狀況 ·
團隊與授權 · 設定（個人資料／安全／隱私與資料／整合與通知）

**Coach** — 團隊總覽 · 選手詳情 · 課表指派. Reached via the workspace switch in
the sidebar, which requires MFA first (REQ-AUTH-007).

## Where the spec lives in the code

The UI is written against `docs/requirements/RunSense_技術規格書_SRS_v3.1.md`.
This table is the traceability record — REQ-tag chips used to be rendered
on-screen for the same purpose, but were removed for a cleaner end-user
interface; this table is now the only place that mapping lives.

**Real** (backend-verified, survives a login) vs **demo** (looks correct but
is `demoData.ts` state — nothing persists, nothing is a real athlete's data):

| Behaviour | Where | Clause | Status |
|---|---|---|---|
| acute / chronic / ratio, data quality, observation days | `src/lib/liveTrainingLoad.ts` | REQ-LOAD-002…006 | Real |
| canonical hash, computed server-side | `TrainingLoadScreen` | REQ-LOAD-007 | Real |
| bounded recompute window (D … D+27) | backend `training_load_store.py` | REQ-LOAD-008 | Real |
| trend numbers only — no traffic lights | `TrainingLoadScreen` | REQ-METRIC-001 / REQ-ALERT-001 | Real |
| durable local commit before "已儲存" | `WorkspaceContext.logActivity` | REQ-SYNC-001 | Real |
| per-account local queue, cleared on logout | `pendingQueueKey` | REQ-LOCAL-SEC-001/003 | Real |
| access token in memory, never localStorage | `AuthContext` | REQ-AUTH-006 | Real |
| activity history, cursor-paginated | `HistoryScreen` | REQ-DATAOWN-001 | Real |
| real weather, four-state fallback | `DashboardScreen` weather card | REQ-WEATHER-001/LOCATION-001 | Real |
| LLM picks a `tone_variant_id` from a reviewed whitelist | `DashboardScreen` guidance card | REQ-AI-004…007 | Real |
| local_training_date from UTC + athlete timezone | `LogWorkoutScreen`, `format.ts` | REQ-TZ-001 | Real |
| coach roster: per-athlete load/status/scope projection | `TeamOverviewScreen` | REQ-DATAOWN-001 | Real |
| coach athlete detail: same projection, single athlete | `AthleteDetailScreen` | REQ-DATAOWN-001 | Real |
| MFA on role elevation, step-up on risky actions | `AppShell`, `StepUpModal` | REQ-AUTH-007/008 | Real (`POST /me/settings/mfa/verify` persists mfa_satisfied on the session; the UI gate itself stays a synchronous local check against the same fixed code, see "Two data modes" above) |
| session list, revoke, current-session marker | `SecuritySettings` | REQ-AUTH-005 | Real |
| account activity log | `SecuritySettings` | REQ-AUDIT-001/002 | Real (only `AUTH_LOGIN` and `DATA_EXPORT` are emitted by this change; `CONSENT_GRANT`/`CONSENT_REVOKE` await Item 2's backend emitting them) |
| actor ≠ target athlete id | `AuthContext.canViewAthlete` | REQ-RLS-006 | Demo (illustrative) |
| injury summary and free text as separate scopes | `BodyStatusScreen`, coach screens | REQ-RLS-007 | Demo (backend field-gating is real; injury data itself has no model yet — Item 3) |
| per-scope consent, revocation timing, leaving a team | `TeamScreen` | REQ-CONSENT-001…004 | Demo |
| duplicates flagged, never auto-merged or deleted | `HistoryScreen` | REQ-DEDUP-002 | Demo (backend doesn't implement this yet) |
| Garmin behind a feature flag, with its preconditions | `IntegrationSettings` | REQ-GARMIN-001/002 | Real flag read (`GET /me/settings/integrations/garmin`) / Demo preconditions checklist (no Developer Program review has actually happened) |
| export / delete request recorded | `PrivacySettings` | REQ-PRIV-001…003/005 | Real export + Real deletion-request timestamp (no retention-period deletion pipeline runs — see backend/README.md) |
| correct / restrict processing | `PrivacySettings` | REQ-PRIV-004/006 | Demo (LLM-tone toggle and policy-version display are client-side only; no backend endpoint for either) |
| coach creates/lists team assignments; athlete's own cross-team view | `AssignmentsScreen` | Assigned Workout (CONTEXT.md) | Real |

## Two demo-only affordances

Both are labelled as such in the UI, and neither would exist in a shipped build:

- **連線 / 離線切換** in the top bar, to show the offline queue and retry path.
- **模擬 Garmin flag 已開啟** in 整合與通知, to show what happens when `AU` and
  `garmin_epoc` records coexist: not summed, shown separately, quality → LOW.

## Charts

Hand-written SVG in `src/components/charts.tsx`. Bars cap at 24px with a 4px
rounded cap on a square baseline, lines are 2px, markers carry a 2px surface
ring, gridlines are solid hairlines, and every plotted chart has a hover
tooltip. Series colors are the first slots of a CVD-validated palette
(blue `#2a78d6` / orange `#eb6834`, re-stepped for the dark surface), and the
trend chart ships a table view so no value is gated behind color.

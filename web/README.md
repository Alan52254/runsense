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
history, training load, and the "今天是休息日" rest-day action hit the real
endpoints:

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

`src/data/apiClient.ts` connects authentication, activity creation and history,
rest-day confirmation, training-load trends, profile settings, weather, and
daily guidance to the live backend. Coach screens, injury reports, consent,
sessions, audit log, and Team still use demo data until their APIs are added.

Two things worth knowing about how the real data is wired:

- **History** merges the real `GET /activities` fetch with the existing
  offline-first local queue (unsynced/failed writes), deduped by
  `client_mutation_id`, so an in-flight save is never lost or double-shown.
- **Rest-day confirmations only reflect the current browser session** in the
  daily chart's rest-vs-missing marker (there is no `GET /rest-days` list
  endpoint yet, only the single-date `PUT`) — a rest day confirmed on a
  previous login shows as "missing," not "rest," until that endpoint exists.
  The server's own `observation_days`/`data_quality` numbers are unaffected;
  only this chart's day marker is approximate.

Demo credentials come from `backend/scripts/seed_demo_personas.py`. The MFA and
step-up challenges accept the fixed code `424242`.

## Screens

**Athlete** — 今日總覽 · 記錄訓練 · 訓練紀錄 · 訓練負荷 · 身體狀況 ·
團隊與授權 · 設定（個人資料／安全／隱私與資料／整合與通知）

**Coach** — 團隊總覽 · 選手詳情 · 課表指派. Reached via the workspace switch in
the sidebar, which requires MFA first (REQ-AUTH-007).

## Where the spec lives in the code

The UI is written against `docs/requirements/RunSense_技術規格書_SRS_v3.1.md`.
The `REQ-…` chips on screen are not decoration — they mark the clause a piece of
UI implements, so a reviewer can check the behaviour against the document.

| Behaviour | Where | Clause |
|---|---|---|
| acute / chronic / ratio, data quality, observation days | `src/lib/trainingLoad.ts` | REQ-LOAD-002…006 |
| canonical JSON → SHA-256 `input_snapshot_hash` | `src/lib/trainingLoad.ts` | REQ-LOAD-007 |
| bounded recompute window (D … D+27) | `recomputeWindowFor` | REQ-LOAD-008 |
| trend numbers only — no traffic lights, no "警示" | `TrainingLoadScreen` | REQ-METRIC-001 / REQ-ALERT-001 |
| durable local commit before "已儲存" | `WorkspaceContext.logActivity` | REQ-SYNC-001 |
| per-account local queue, cleared on logout | `pendingQueueKey` | REQ-LOCAL-SEC-001/003 |
| access token in memory, never localStorage | `AuthContext` | REQ-AUTH-006 |
| MFA on role elevation, step-up on risky actions | `AppShell`, `StepUpModal` | REQ-AUTH-007/008 |
| actor ≠ target athlete id | `AuthContext.canViewAthlete` | REQ-RLS-006 |
| injury summary and free text as separate scopes | `BodyStatusScreen`, coach screens | REQ-RLS-007 |
| per-scope consent, revocation timing, leaving a team | `TeamScreen` | REQ-CONSENT-001…004 |
| duplicates flagged, never auto-merged or deleted (demo data only — the backend doesn't implement REQ-DEDUP-002 yet) | `HistoryScreen` | REQ-DEDUP-002 |
| LLM picks a `tone_variant_id` from a reviewed whitelist | `DashboardScreen` | REQ-AI-004…007 |
| Garmin behind a feature flag, with its preconditions | `IntegrationSettings` | REQ-GARMIN-001/002 |
| export / correct / delete / restrict processing | `PrivacySettings` | REQ-PRIV-001…006 |
| local_training_date from UTC + athlete timezone | `LogWorkoutScreen`, `format.ts` | REQ-TZ-001 |

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

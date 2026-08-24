# RunSense MVP handoff

## Delivered scope

- Athlete: dashboard, manual workout entry, activity history, rest-day confirmation, training-load trend,
  body-status reporting, team invitations, membership lifecycle, and per-team consent controls.
- Coach: team discovery, consent-filtered roster, and athlete detail.
- Coach assignments: create and list team-owned workouts for active roster members; athletes can read their
  own assigned workouts.
- Settings: demo-session management and MFA verification, account activity, data export, deletion request,
  and server-gated Garmin integration status.
- Data protection: the coach remains the database actor; PostgreSQL RLS checks current membership and the
  four independent consent scopes (`activity_summary`, `training_load`, `injury_status`, `injury_detail`).
- Body status: summary and free text use separate tables and separate RLS policies.
- Demo identity: three seeded personas with a team, training history, consent combinations, and body-status
  examples.
- Interface: responsive desktop/mobile shell, five-item mobile navigation with an overflow bottom sheet,
  endurance-sport visual tokens, accessible focus states, Escape-to-close dialogs, and reduced-motion support.

The agreed MVP boundary and deferred work are recorded in [mvp-checklist.md](mvp-checklist.md).

## Start the backend

From `backend/` in PowerShell:

```powershell
docker compose up -d
$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/runsense"
$env:COMPETITION_DEMO_ONLY = "true"
$env:DEMO_JWT_SECRET = "runsense-competition-demo-secret-2026-change-before-release"
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
& ".\.venv\Scripts\python.exe" ".\scripts\seed_demo_personas.py"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API health check is `http://127.0.0.1:8000/health`.

## Start the web app

In a second PowerShell window, from `web/`:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev -- --host 0.0.0.0
```

Open `http://127.0.0.1:5173`. If `VITE_API_BASE_URL` is omitted, the interface intentionally uses its
built-in presentation dataset.

## Demo Personas

| Persona | Email | Password | Best demo path |
|---|---|---|---|
| Taipei coach | `runner.taipei@runsense.demo` | `TaipeiDemo!2026` | Switch to coach view, inspect roster consent projection |
| Tokyo athlete | `runner.tokyo@runsense.demo` | `TokyoDemo!2026` | Team consent and injury-summary sharing |
| London athlete | `runner.london@runsense.demo` | `LondonDemo!2026` | Independent injury-detail sharing |

The coach-view MFA demonstration code is `424242`.

## Verification

Backend, with PostgreSQL running and the demo environment variables above:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/runsense"
& ".\.venv\Scripts\python.exe" -m pytest -q
```

Expected result at handoff: `181 passed`.

Frontend:

```powershell
npm run build
```

The production TypeScript/Vite build passes. Responsive QA covers a 390 × 844 phone viewport and a desktop
viewport, including access to the mobile overflow routes.

## Deferred boundary

Real authentication, live Garmin activity ingestion, native mobile GPS recording, compliance-grade account
deletion, and live deployment are intentionally outside this local web MVP. Do not infer these capabilities
from the demo identity or guarded integration status.

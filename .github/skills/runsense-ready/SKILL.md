---
name: runsense-ready
description: "Prepare the RunSense workspace to open and use the web app after code changes. Use when the user asks to finish setup, start the app, open the webpage, verify the backend/frontend, run all pre-launch steps, or fix startup failures."
argument-hint: "Optional: specify frontend-only, backend-only, or full stack"
user-invocable: true
disable-model-invocation: false
---

# RunSense Ready

Prepare this workspace for local use after implementation or bug fixes. Work in the existing workspace and preserve unrelated user changes.

## Completion Criteria

Do not claim the app is ready until:

- `backend/.venv` exists and uses Python 3.11 or newer.
- Backend dependencies from `backend/pyproject.toml` are installed.
- PostgreSQL is running through `backend/docker-compose.yml`, when Docker is available.
- `DATABASE_URL` is set for the current PowerShell session.
- Alembic migrations have completed successfully.
- Demo mode has `COMPETITION_DEMO_ONLY=true` and a non-empty `DEMO_JWT_SECRET` when demo login is needed.
- The backend responds at `http://127.0.0.1:8000/docs`.
- Web dependencies are installed and `npm run build` passes.
- The web dev server responds at `http://localhost:5173` or the actual Vite port.
- The final response states which terminals must remain open and gives the URLs.

## Procedure

1. Identify the workspace root from the current files. Use `backend/`, `web/`, and `client/` relative to that root.
2. Inspect the current terminal state and existing files before changing anything. Check `backend/pyproject.toml`, `backend/docker-compose.yml`, `backend/.env.example`, `web/package.json`, and `web/vite.config.ts`.
3. Check prerequisites with PowerShell: `py -0p`, `node --version`, `npm --version`, and `docker --version`. Use Python 3.11+ explicitly; do not use the default Python if it is 3.9.
4. If `backend/.venv` is missing, create it with `py -3.11 -m venv backend/.venv`. Install with `backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"` only when run from the workspace root, or `pip install -e ".[dev]"` from `backend`.
5. Start PostgreSQL from `backend`: `docker compose up -d`. Check `docker compose ps`. If Docker is unavailable, report that the backend cannot be fully verified and continue with frontend-only validation.
6. Set runtime variables in the same PowerShell session used for backend commands:
   - `$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/runsense"`
   - `$env:COMPETITION_DEMO_ONLY="true"` for demo login
   - `$env:DEMO_JWT_SECRET` must be supplied by the user or loaded from their local ignored environment; never invent or print a real secret
   - `$env:OPENWEATHER_API_KEY` is optional; never ask the user to paste a secret into chat
   - `$env:CORS_ALLOWED_ORIGINS="http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"`
7. Run migrations with `backend/.venv/Scripts/python.exe -m alembic upgrade head` from `backend`. If demo personas are required, run `backend/.venv/Scripts/python.exe scripts/seed_demo_personas.py` after migrations.
8. Start the backend with `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000` from `backend`. Keep this process running. Do not start a second backend on the same port. Verify `/docs` with an HTTP request or browser when available.
9. From `web`, run `npm install` if `node_modules` is missing, then run `npm run build`. Fix only relevant errors and rerun the same focused command.
10. Start the frontend with `npm run dev -- --host localhost` from `web`, setting `$env:VITE_API_BASE_URL="http://127.0.0.1:8000"` first when the live backend should be used. Keep this process running. If port 5173 is occupied, use the Vite-reported port.
11. Verify the final frontend URL and backend docs URL. If browser tools are available, open the frontend URL and check that the page is nonblank. Do not use browser automation to expose secrets.
12. Report a concise readiness result: completed checks, any skipped checks, frontend URL, backend docs URL, and exact stop commands (`Ctrl+C`).

## Error Handling

- If a command is skipped or terminal execution is unavailable, do not claim it succeeded. Tell the user the exact command to run.
- If `uvicorn` is not recognized, use the virtual-environment form `backend/.venv/Scripts/python.exe -m uvicorn`.
- If `Activate.ps1` is blocked or missing, do not depend on activation; invoke the virtual-environment Python executable directly.
- If the backend fails because PostgreSQL is unreachable, check Docker status and migration/database configuration before changing application code.
- If frontend build fails, fix the smallest relevant code issue and rerun `npm run build` before launching the dev server.
- Never write real API keys, JWT secrets, passwords, or tokens into tracked files. `.env` is ignored; `.env.example` must contain placeholders only.
- Do not treat an OpenWeatherMap key as a prerequisite for startup. It only enables live weather; the app has an unavailable fallback.

## Expected Commands

PowerShell commands should be run one at a time, with the correct working directory:

```powershell
cd C:\Users\erics\Downloads\runsense-main\backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
docker compose up -d
$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/runsense"
$env:COMPETITION_DEMO_ONLY="true"
$env:DEMO_JWT_SECRET="use-your-local-demo-secret"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\seed_demo_personas.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

In a second PowerShell:

```powershell
cd C:\Users\erics\Downloads\runsense-main\web
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
npm install
npm run build
npm run dev -- --host localhost
```

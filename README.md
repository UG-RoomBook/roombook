# RoomBook

Study-room search, booking and cancellation. The [engineering wiki](https://github.com/UG-RoomBook/wiki) records the application architecture and delivery plan. The [approved design archive](docs/design/baselines/v1/README.md) remains the visual reference.

## Local frontend

Use the Node/npm versions recorded in `frontend/package.json` and install from the committed lockfile.

```text
cd frontend
npm ci
npm run dev
```

Vite serves the frontend on the local URL printed in the terminal and proxies API requests to `http://127.0.0.1:8000`. Copy `frontend/.env.example` to `frontend/.env.local` to configure another backend target. Keep credentials out of Vite environment variables; they become browser-visible configuration.

For local sample data without a backend, set `VITE_ENABLE_MOCKS=true` in `.env.local` and restart Vite. The footer identifies this mode as **Demo data**. It uses MSW with synthetic rooms/bookings, resets on reload and has no effect in a production build. Default mode always uses the real API.

## Local backend

Use Python 3.12.14, uv 0.13.1 and Docker Desktop with its Linux engine. From the repository root, start the local database and copy the development configuration:

```powershell
docker compose -f compose.dev.yml up -d --wait db
Copy-Item backend/.env.example backend/.env
cd backend
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -m scripts.seed_rooms
$env:ROOMBOOK_COMMIT_SHA = git rev-parse HEAD
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Copy the example configuration only for the initial setup. The database listens on `127.0.0.1:5433`; its sample credentials are for local development. The digest-pinned PostgreSQL image creates separate `roombook` and `roombook_test` databases on its first initialization. Room seeding inserts missing reference rooms without replacing existing records or creating bookings. Migrations and seeding are explicit commands, not application startup actions.

`/health` checks process health, `/ready` checks database connectivity and `/version` returns configured runtime identity. Without `ROOMBOOK_COMMIT_SHA`, the API reports `unknown`. Readiness returns 503 when the database is unavailable; health/version and OpenAPI export remain independent of a database connection. Runtime configuration belongs to Bhathiya; CI/CD wiring belongs to Prattay.

## Backend checks

Run from `backend/`, explicitly selecting the isolated test database in PowerShell before the checks:

```powershell
$env:ROOMBOOK_TEST_DATABASE_URL = 'postgresql+psycopg://roombook:roombook@127.0.0.1:5433/roombook_test'
```

```text
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest --cov=app --cov-report=term-missing --cov-report=xml
uv run --locked alembic check
uv run --locked python scripts/export_openapi.py --check
```

Database tests refuse to reset a database whose name does not end in `_test`. They require real PostgreSQL and do not replace it with SQLite or silently count skipped database checks as acceptance. The exported `backend/openapi.json` contains only implemented routes. Update it with `uv run --locked python scripts/export_openapi.py`; it does not require database credentials or a running database. The frontend contract remains provisional until the integration tickets reconcile implemented and pending booking operations.

## Frontend checks

Run these from `frontend/`:

```text
npm run api:check
npm run format:check
npm run lint
npm run typecheck
npm test
npm run test:coverage
npm run build
```

The frontend PR workflow runs these checks on a GitHub-hosted runner and keeps coverage reports. Component tests use MSW. They verify frontend behaviour and do not establish real FastAPI/PostgreSQL acceptance. Required browser journeys, candidate image promotion, Test-host checks and operational tests remain with their Jira owners.

See the [frontend verification record](docs/frontend/verification-2026-10-18.md) for local checks, browser evidence and remaining acceptance work.

## Backend handoff

`frontend/openapi/roombook.json` is a **provisional frontend development contract** transcribed from the accepted wiki, not a FastAPI export. Saad owns application/backend implementation; Daniel owns test strategy and independent integration/acceptance testing. Reconcile response schemas, stable operation IDs, error envelopes and `items/total/limit/offset` pagination with the backend's exported OpenAPI before accepting real integration. Regenerate with `npm run api:generate`; never edit `src/shared/api/generated/` manually.

The app uses relative `/api/v1/rooms`, `/api/v1/bookings`, cancellation and `/version` endpoints. Melbourne dates become explicit-offset timestamps; booking creation is never automatically retried. An uncertain outcome keeps its selection and directs the user to check bookings. The affected review URL and mutation cache guard against another submission; without backend request reconciliation or persisted idempotency, an empty refreshed list cannot prove a timed-out request will never complete. Real timeout acceptance remains pending integration.

Shared booking room names use cached metadata with bounded pagination; datasets above 2,000 rooms produce an explicit lookup error and need a revised lookup contract.

## Work tracking

[RoomBook Jira](https://swe40006-roombook.atlassian.net) tracks acceptance and ownership. This frontend work covers RB-12 and prepares the UI for RB-14, RB-16 and RB-18. Those integration stories require the real backend. Loading, empty, failure, conflict and timeout visuals remain pending visual review where the approved prototype does not demonstrate them. The v1 archive is immutable.

# RoomBook

Study-room search, booking and cancellation. The [engineering wiki](https://github.com/UG-RoomBook/wiki) records the application architecture and delivery plan. The [approved design archive](docs/design/baselines/v1/README.md) remains the visual reference.

The current delivery baseline is the [submitted AWS plan restored by ADR-012](https://github.com/UG-RoomBook/wiki/blob/main/decisions/ADR-012-restore-submitted-aws-pipeline.md): three EC2 roles, Docker Compose and self-hosted GitHub Actions runners. The [K3s hosting foundation](deploy/kubernetes/README.md) and its [verification record](docs/operations/RB-10-verification.md) preserve the earlier Contabo work as historical evidence; they do not define the current deployment plan.

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

`GET /api/v1/rooms` returns `items`, `total`, `limit` and `offset`, ordered by room name then ID. The default page size is 20, the maximum is 100, and offsets must fit a nonnegative signed 64-bit integer. Without an interval, responses contain room metadata and omit `available`. Supply both `starts_at` and `ends_at` as ISO 8601 timestamps with explicit offsets to receive boolean availability. Intervals use UTC instants and half-open boundaries: a booking ending at the selected start or starting at the selected end does not overlap. Cancelled bookings do not block rooms; inactive rooms remain unavailable. Availability is advisory until booking creation commits.

For example, `http://127.0.0.1:8000/api/v1/rooms?starts_at=2026-10-19T02%3A00%3A00Z&ends_at=2026-10-19T03%3A00%3A00Z&limit=20&offset=0` checks 13:00–14:00 in Melbourne on that date. Missing interval partners, naive timestamps, invalid ranges and out-of-bounds pagination return the shared 422 error envelope; an unavailable database returns 503. The frontend uses this implemented room contract. Booking endpoints remain pending.

Room search keeps applied filters and pagination in the URL. Group size filters the current API page, so paginated counts and empty states describe that page. Availability is withheld while refreshing; failed requests show retry feedback and a request ID when supplied. Metadata without a selected interval does not claim availability. See the [RB-14 verification record](docs/frontend/RB-14-verification.md) for real browser/API observations and remaining acceptance work.

## Backend checks

RB-45 adds application identity mapping and server-side session foundations. See the
[session setup and operations guide](docs/backend/RB-45-sessions.md) for environment
settings, expiry, refresh, revocation and migration behaviour. RB-46 adds registration,
verification/resend, login/logout, password recovery and email change through FastAPI,
with account screens at `/account`. Authentication remains disabled until configured.
Use the [account setup guide](docs/backend/RB-46-accounts.md) to configure the exact
email templates and same-origin callback, then follow the
[account verification record](docs/backend/RB-46-verification.md). Live Staging mail
and independent acceptance remain pending under RB-46/RB-48. Public discovery remains
available without a session.

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

Database tests refuse to reset a database whose name does not end in `_test`. They require real PostgreSQL and do not replace it with SQLite or silently count skipped database checks as acceptance. The exported `backend/openapi.json` contains only implemented routes. Update it with `uv run --locked python scripts/export_openapi.py`; it does not require database credentials or a running database. The frontend generator reads that export directly.

See the [backend verification record](docs/backend/verification-2026-10-18.md) for measured local results, room availability behaviour and remaining integration/acceptance work.

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

`backend/openapi.json` is the source for the pinned Hey API generator. Saad owns application/backend implementation; Daniel owns test strategy and independent integration/acceptance testing. After an API change, export the schema from `backend/`, run `npm run api:generate` from `frontend/`, and commit both the schema and generated output. Never edit `src/shared/api/generated/` manually. `npm run api:check` regenerates outside the checkout and fails on drift without changing tracked files. Run the separate backend export check to detect implementation/schema drift.

Real mode calls relative `/api/v1/rooms` and `/version` endpoints. Melbourne dates become explicit-offset timestamps. The existing booking screens use a separate provisional adapter for opt-in development MSW and tests; real mode reports booking as unavailable without sending an unimplemented booking request. Replace that adapter with generated operations when owned booking APIs are implemented in RB-15 through RB-18.

In the development booking demonstration, creation is never automatically retried. An uncertain outcome keeps its selection and directs the user to check bookings. Without backend reconciliation or persisted idempotency, an empty refreshed list cannot prove a timed-out request will never complete. Real booking/timeout acceptance remains pending integration.

Shared booking room names use cached metadata with bounded pagination; datasets above 2,000 rooms produce an explicit lookup error and need a revised lookup contract.

## Work tracking

[RoomBook Jira](https://swe40006-roombook.atlassian.net) tracks acceptance and ownership. RB-12 provides the frontend foundation; RB-14 integrates public room discovery with the real API. RB-16 and RB-18 still require owned booking APIs and identity integration. Loading, empty, failure, conflict and timeout visuals remain pending visual review where the approved prototype does not demonstrate them. The v1 archive is immutable.

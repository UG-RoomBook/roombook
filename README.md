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

`frontend/openapi/roombook.json` is a **provisional frontend development contract** transcribed from the accepted wiki, not a FastAPI export. It enables parallel frontend work while Daniel builds the backend. Reconcile response schemas, stable operation IDs, error envelopes and `items/total/limit/offset` pagination with the backend's exported OpenAPI before accepting real integration. Regenerate with `npm run api:generate`; never edit `src/shared/api/generated/` manually.

The app uses relative `/api/v1/rooms`, `/api/v1/bookings`, cancellation and `/version` endpoints. Melbourne dates become explicit-offset timestamps; booking creation is never automatically retried. An uncertain outcome keeps its selection and directs the user to check bookings. The affected review URL and mutation cache guard against another submission; without backend request reconciliation or persisted idempotency, an empty refreshed list cannot prove a timed-out request will never complete. Real timeout acceptance remains pending integration.

Shared booking room names use cached metadata with bounded pagination; datasets above 2,000 rooms produce an explicit lookup error and need a revised lookup contract.

## Work tracking

[RoomBook Jira](https://swe40006-roombook.atlassian.net) tracks acceptance and ownership. This frontend work covers RB-12 and prepares the UI for RB-14, RB-16 and RB-18. Those integration stories require the real backend. Loading, empty, failure, conflict and timeout visuals remain pending visual review where the approved prototype does not demonstrate them. The v1 archive is immutable.

# Browser journeys

Playwright journeys against a real RoomBook instance (React, FastAPI and
PostgreSQL). The candidate pipeline runs them on the Test server twice: against
the disposable Testing stack, then against Staging over HTTPS. They never run
against MSW mocks.

| Journey | Covers |
|---|---|
| `discovery.spec.ts` | Release identity in the footer, seeded rooms, dropdown duration boundaries (30 minutes–2 hours), interval search with availability, client-route fallback and JSON 404s |

Booking, conflict and cancellation journeys join this folder when the booking
API (RB-15 to RB-18) is merged.

Run locally against any instance:

```text
cd tests/e2e
npm ci
npx playwright install chromium
$env:BASE_URL = "http://127.0.0.1:8000"   # PowerShell
npx playwright test
```

Optional `EXPECTED_COMMIT` and `EXPECTED_ENVIRONMENT` make the first journey
check the footer's runtime identity.

## Authenticated room-first fixture journeys

`specs/room-booking.spec.ts` performs writes only when `ROOMBOOK_E2E_FIXTURE=1`
and `BASE_URL=http://127.0.0.1:8011`. The candidate and Staging smoke suite skips
these fixture-only cases. The reusable `room-booking.yml` workflow runs them on
PRs and before the candidate image build, with PostgreSQL and the built frontend.

For local verification, create a **new empty** localhost PostgreSQL database whose
name ends in `_e2e_test`, build the frontend, then from `backend` run:

```sh
ROOMBOOK_DATABASE_URL="$ROOMBOOK_E2E_DATABASE_URL" uv run --locked alembic upgrade head
uv run --locked uvicorn tests.e2e_server:app --host 127.0.0.1 --port 8011
```

Set `ROOMBOOK_E2E_DATABASE_URL` explicitly to that disposable database first.
The server refuses existing room data and never resets a database. It creates
synthetic confirmed room hours, a known occupied gap, and real database-backed
sessions backed by a deterministic external identity double. The fixture routes
are outside `app/` and never enter the production image. With the server running:

```sh
BASE_URL=http://127.0.0.1:8011 ROOMBOOK_E2E_FIXTURE=1 npm test -- --workers=1
```

The fixture clock is 18 October 2026; write journeys use 19 October 2026. Run them
against a fresh fixture database each time. Screenshots in `results/` include
mobile and desktop Light/Dark layouts. Trace retention covers failed assertions;
never run fixture writes against Staging. A controlled real Staging account and
operator-confirmed hours are a separate release acceptance gate.

# Browser journeys

Playwright journeys against a real RoomBook instance (React, FastAPI and
PostgreSQL). The candidate pipeline runs them on the Test server twice: against
the disposable Testing stack, then against Staging over HTTPS. They never run
against MSW mocks.

| Journey | Covers |
|---|---|
| `discovery.spec.ts` | Release identity in the footer, seeded rooms, interval search with availability, client-route fallback and JSON 404s |

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

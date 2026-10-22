# RB-16: authenticated booking review and safe submission

Implemented and verified locally on 22 October 2026. Source:
[`29c734d41a997b8ec3ee80648c3e339119e8e6f5`](https://github.com/UG-RoomBook/roombook/commit/29c734d41a997b8ec3ee80648c3e339119e8e6f5),
based on main `e675c8d` (merged RB-57 / PR #20). Jira:
[RB-16](https://swe40006-roombook.atlassian.net/browse/RB-16).
PR review and acceptance remain separate from these observed checks.

## Behavior and recovery

Public discovery stays available. Review requires a verified active standard session,
preserves the room, date, interval, capacity and search offset through sign-in, and
revalidates the session before every submission. The generated `createBooking`
operation uses the application origin, same-origin credentials, current CSRF token
and a UUID idempotency key. Only the room and interval enter the JSON body;
server ownership remains authoritative. Response ownership and interval are validated.

Before POST, the exact payload and key are persisted in session storage under the
user and interval. Pending duplicate clicks/navigation are guarded. Network errors,
timeouts, invalid responses, server failures and `REQUEST_IN_PROGRESS` / `BOOKING_BUSY`
offer an explicit **Retry saved booking** action after a one-second pause. There
are no automatic mutation retries. Retry uses the original key and payload even
when refreshed availability says unavailable or the catalog cannot load. Reload
and a fresh sign-in by the same user retain that attempt. Another user does not
inherit its pending state or receipt.

Storage failure prevents a new POST; corrupt attempts and an unknown-outcome URL
without a key fail closed. Keep the original tab until an uncertain result is
resolved. Session storage is intentionally per tab and ends when that tab is
closed; it is not a cross-device recovery service. No password, session cookie or
CSRF token is persisted. Do not clear a pending key to force a new reservation.

A validated server response shows a booking reference on review. Its saved receipt
survives reload and represents the original creation, not a current status read.
Private history and cancellation remain RB-17/RB-18. Conflict keeps inputs and
refreshes availability. Authentication, permission, validation and throttling
failures preserve the selection and have explicit feedback.

## Observed verification

| Check | Result |
| --- | --- |
| Frontend suite | **157 passed**, 14 files |
| Frontend coverage | **96.77% lines**, 89.62% branches |
| Booking feature coverage | 97.81% lines, 90.58% branches |
| Generated client drift, formatting, ESLint, TypeScript, production build | Passed |
| Backend booking + booking-policy regression suite | **71 passed** against PostgreSQL |
| Manual fixture Ruff, format and strict mypy | Passed |
| Real browser sign-in → preserved review → submission | Passed |
| Lost committed response → reload → same-key reconciliation | Passed; one booking / one request record before and after retry |
| Concurrent competing booking | Real 409; selection retained, availability refreshed, confirm disabled |
| Session revoked before confirmation | Real session 401; no booking POST; same selection restored after sign-in |
| Normal confirmation → reload | Receipt retained; no second POST |
| Themes and responsive checks | Guest, uncertain, conflict, expired-session and success states captured in both themes; receipt fits 375px mobile and 1440px desktop without horizontal overflow |

Raw [frontend tests](evidence/RB-16/frontend-tests.txt),
[frontend checks](evidence/RB-16/frontend-checks.txt),
[backend tests](evidence/RB-16/backend-tests.txt),
[fixture checks](evidence/RB-16/fixture-checks.txt) and
[HTTP server log](evidence/RB-16/api-server.txt) are retained.
Database counts: [before retry](evidence/RB-16/database-before-retry.json),
[after retry](evidence/RB-16/database-after-retry.json).
Screenshots are in [the evidence directory](evidence/RB-16/), including
[normal confirmation](evidence/RB-16/normal-success-light.jpg),
[uncertain outcome](evidence/RB-16/uncertain-dark.jpg) and
[conflict](evidence/RB-16/conflict-light.jpg).

The browser used Vite → real loopback Uvicorn → PostgreSQL 17 with real persisted
server sessions, CSRF/Origin checks and signed synthetic provider tokens. Only
outbound identity was synthetic. The first 201 was deliberately replaced by 503
*after commit*. A separate synthetic account then occupied another interval to
produce a real conflict. Existing development/university data was not changed.
Screenshots identify the working-tree runtime; the final source is pinned above.

## Reproduce the isolated browser check

Start the compose database and migrate a dedicated localhost browser database
ending in `_test`. Use a separate empty database for pytest, because its session
fixture downgrades the schema and correctly refuses to discard existing booking
ownership or retry history. Then from `backend` run:

```bash
ROOMBOOK_TEST_DATABASE_URL='postgresql+psycopg://roombook:roombook@127.0.0.1:5433/roombook_test' \
  .venv/bin/python -m tests.manual_booking_server
```

Run `npm run dev -- --port 5173` from `frontend` using the pinned Node 24 toolchain
and visit `http://127.0.0.1:5173`. Use the explicitly synthetic credentials
`member@example.com` / `synthetic-password-123`. Select the synthetic room, a
future day within 14 days, and a free interval within its synthetic 09:00–17:00
hours. Confirm, observe the injected 503, reload, and retry the saved booking.
The helper binds only loopback, requires a local test database, and never resets
or deletes data. Do not point database-resetting pytest fixtures at this populated browser database.
The final regression run used a fresh `roombook_rb16_test` after the expected
reset refusal against the populated browser database; browser records were retained.
Stop the helper and Vite after checking. The helper is under `tests` and is not
loaded by the production application.

These checks do not qualify hosted identity/mail, AWS deployment or a physical
mobile device. The existing Vite large-chunk warning (~679 kB) and Starlette test
client deprecation remain. Independent PR review and release acceptance are pending.

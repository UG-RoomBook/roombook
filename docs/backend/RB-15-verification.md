# RB-15 verification, 21 October 2026

Implementation source: `ac778498bd691a2e00a64e893037231ef874a500`,
branch `feat/RB-15-owned-bookings`, based on main `c8988eb`.
Owner: Saad.

## Checks and review

| Check | Observed result |
| --- | --- |
| Full backend/PostgreSQL suite | **445 passed** |
| Backend combined coverage | 95.86% |
| Booking service coverage | 98.08% lines, 93.75% branches |
| Ruff lint/format | Passed, 82 files |
| Strict mypy | Passed, 76 source files |
| Alembic upgrade and model drift | Passed at `0005` |
| OpenAPI export and generated client drift | Passed |
| Frontend tests | **117 passed**, 12 files |
| Frontend formatting, ESLint, TypeScript, production build | Passed |
| Localhost HTTP + PostgreSQL smoke | Passed; original 201 replayed with one booking and one retry record |

Raw [backend checks](evidence/RB-15-backend-checks.txt),
[frontend checks](evidence/RB-15-frontend-checks.txt), and
[HTTP smoke](evidence/RB-15-http-smoke.json) are retained. Runs used the pinned
workspace toolchain and locked dependencies. Existing Starlette/httpx deprecation,
npm configuration and frontend bundle-size warnings remain visible.

Code review checked server-derived ownership, standard-session/Origin/CSRF
requirements, private success/error responses, normalized payload identity,
transaction commit/rollback, lock order, the named exclusion mapping and
preservation of existing rows. No blocking defect remained after verification.

## What the tests establish

The booking suite exercises real PostgreSQL commits, rollback after an inserted
booking but failed result write, concurrent same-key handling, mismatch and
cross-user key isolation, different-key book/book races, both book/closure orders,
adjacent intervals and the database exclusion backstop when a precheck misses an
overlap. Lock timeout is retryable without consuming a key. Unrelated integrity
errors are not mislabeled as availability conflicts.

HTTP integration uses real persisted server sessions with a deterministic
synthetic identity provider. Guest, expired, revoked, recovery and inactive
accounts are denied. Owner/status injection, missing/wrong Origin/CSRF,
cross-site requests, malformed keys and invalid intervals are rejected without
creating records. Replays stay identical after cancellation and passage of time.
Errors and successful responses have private/no-store headers.

The additional localhost smoke used Uvicorn over an actual loopback TCP socket,
HTTPX and isolated PostgreSQL. It observed 401 guest, 422 owner injection, 201
create and exact 201 replay, 409 mismatch and other-user overlap, 204 logout and
401 revoked retry. Exactly one booking and one successful retry record existed.
Only the smoke's synthetic records were removed afterward. This does not test a
hosted identity provider or delivered mail.

## Data preservation and rollout

Migration tests start at the prior schema, preserve original unowned booking
values and IDs across upgrade and empty downgrade, and reject a populated
ownership/retry downgrade without losing data. The aggregate legacy inventory
works before and after migration and excludes owned bookings after upgrade.

The development database was migrated to `0005`; its
[calendar inventory](evidence/RB-15-calendars-after.json) records three rooms,
zero bookings and two rooms without confirmed hours. Its
[unowned inventory](evidence/RB-15-ownership-after.json) is zero. The two reference
rooms remain unconfirmed; the separate synthetic calendar remains local only.
No shared or AWS database was modified.

Follow the [contract and recovery guide](RB-15-bookings.md). Frontend submission
integration is RB-16; private history/cancellation follows in RB-17/RB-18. Image,
AWS and hosted mail qualification require their own runtime evidence.

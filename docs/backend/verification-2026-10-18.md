# Backend verification, 18 October 2026

This records the implemented RB-11 foundation and RB-13 room API. Saad owns application implementation; Daniel owns independent testing and acceptance. Automated technical review does not record teammate approval.

## Environment and commands

Checks ran on Windows with Python 3.12.14 and uv 0.13.1 against PostgreSQL 17.11 (Debian 17.11-1.pgdg13+2). The local Compose image digest is `sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`. PostgreSQL listens on `127.0.0.1:5433`; the application database is `roombook` and tests use the separate `roombook_test` database. The sample credentials below are local development values.

Run from `backend/` in PowerShell:

```powershell
$env:ROOMBOOK_DATABASE_URL = 'postgresql+psycopg://roombook:roombook@127.0.0.1:5433/roombook'
$env:ROOMBOOK_TEST_DATABASE_URL = 'postgresql+psycopg://roombook:roombook@127.0.0.1:5433/roombook_test'
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest --cov=app --cov-report=term-missing --cov-report=xml
uv run --locked alembic check
uv run --locked python scripts/export_openapi.py --check
```

All commands passed. Ruff checked 35 Python files and mypy checked 33 source files. The suite passed 101 cases with no skips, including real PostgreSQL migration, schema, session and room API checks. Coverage of `app` was 300/305 lines (98.36%) and 30/34 branches (88.24%), or 97.35% combined. Scripts and tests are outside that measured application scope. One third-party Starlette/httpx deprecation warning remains; it did not fail the checks. Alembic reported no new upgrade operations, and the exported OpenAPI matched the implemented routes.

## Verified behaviour

The schema checks cover positive room capacity, unique names, booking foreign keys, valid intervals and cancellation state, plus the named active-room exclusion constraint. Adjacent intervals and cancelled records do not conflict. Migrations pass downgrade/upgrade and repeated upgrade; room seeding is idempotent, preserves existing records and creates no bookings. Request sessions are independent, uncommitted work rolls back, database statements have timeouts, and readiness detects an unreachable database. Health and version do not query PostgreSQL; public errors redact internal details and include a request ID.

`GET /api/v1/rooms` returns room metadata without inventing availability when no interval is supplied. Paired explicit-offset timestamps are normalized to UTC. Availability uses two SQL queries per page: a total count, then one ordered page with a correlated `EXISTS` for active booking overlaps. The overlap predicates are `booking.starts_at < requested_end` and `booking.ends_at > requested_start`; active rooms without an overlap are available. Cancelled bookings do not block rooms and inactive rooms remain unavailable. Tests cover overlap shapes, adjacent boundaries, equivalent offsets across daylight saving, room isolation, empty pages and stable name/ID ordering without one query per room.

Pagination defaults to 20 rooms, caps the page size at 100 and accepts offsets from zero through `9223372036854775807`. The maximum offset returns a valid empty page against PostgreSQL. Missing timestamp partners, naive or invalid timestamps, UTC conversion overflow and unsupported pagination return the shared 422 envelope. Connection failures return sanitized 503 responses. Availability remains advisory until booking creation commits.

## Scope and remaining work

The committed backend OpenAPI exposes only `/health`, `/ready`, `/version` and `/api/v1/rooms`. The provisional frontend contract and SDK remain separate until RB-14 reconciles the contracts and verifies the real browser/API path with mocks disabled. The [earlier frontend verification](../frontend/verification-2026-10-18.md) records its historical development-data checkpoint; the ownership above reflects the subsequent allocation.

Booking creation/listing and cancellation APIs remain RB-15/RB-17 work, including real concurrent booking and transaction acceptance. Backend CI/CD wiring remains Prattay's responsibility; the backend results here are local checks. Production and monitoring qualification remain Bhathiya's responsibility. Daniel's independent verification and designated teammate acceptance remain pending. This record does not complete M1, deployment or operational gates, and the approved v1 design archive is unchanged.

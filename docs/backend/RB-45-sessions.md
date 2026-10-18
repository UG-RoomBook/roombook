# RB-45: Identity mapping and server sessions

Implementation owner: Saad. Independent reviewer: Daniel.

Follows [ADR-008](https://github.com/UG-RoomBook/wiki/blob/4e0fdbd440d8ac755e7e57ac97fb73aebb51abd6/decisions/ADR-008-hosted-identity-and-email.md).
Supabase.com manages identity credentials; the existing application PostgreSQL owns
users, roles and browser sessions. There is no Supabase browser SDK or public
provider-token exchange endpoint. RB-46 supplies registration, login, recovery,
email callbacks and account screens. RB-47 supplies administrator/MFA actions.

## Configuration

Authentication defaults to disabled. Room discovery, operational endpoints and schema
export continue to work without provider credentials. Auth routes return a safe 503
while disabled. Enable only after supplying all required settings through protected
server configuration; never put them in Vite variables, Git, Jira or evidence.

| Variable | Meaning |
| --- | --- |
| `ROOMBOOK_AUTH_ENABLED` | Explicit feature enablement, default `false` |
| `ROOMBOOK_AUTH_SUPABASE_URL` | Selected environment's HTTPS project origin |
| `ROOMBOOK_AUTH_SUPABASE_PUBLISHABLE_KEY` | Matching project publishable key; no service-role key needed |
| `ROOMBOOK_AUTH_TOKEN_ENCRYPTION_KEY` | Environment-specific Fernet key, held outside the database and backups |
| `ROOMBOOK_AUTH_SITE_URL` | Exact browser origin, without path/query; used for Origin validation |
| `ROOMBOOK_AUTH_COOKIE_SECURE` | Defaults `true`; `false` only for explicit development/test loopback HTTP |
| `ROOMBOOK_AUTH_IDLE_SECONDS` | Default 1,800 seconds (30 minutes) |
| `ROOMBOOK_AUTH_ABSOLUTE_SECONDS` | Default 43,200 seconds (12 hours); never extended by refresh |
| `ROOMBOOK_AUTH_REVALIDATE_SECONDS` | Default and maximum 300 seconds (5 minutes) |

RB-48 selected Staging project `uvgcoknpnvnnkyuqmrzw` and Production project
`tnzexsipsggzevccffgl`, both in Sydney. Use matching project configuration and separate
encryption keys. SMTP credentials remain in Supabase settings, outside this service.
Saad provisions and protects secrets; Prattay wires CI secrets; Bhathiya verifies
runtime configuration and recovery. No live configuration was installed by this code.

Create a Fernet key privately using the cryptography library or a protected operator
tool. Do not print it into shared terminals or capture it in evidence. Back up the key
separately from the database. Losing or replacing it invalidates encrypted provider
tokens and CSRF values: revoke local sessions and require sign-in when rotating it.
Do not mix encryption keys between environments or restore old sessions as active.

## Data and migration

Migration `0002` adds `application_users`, `external_identities`, `auth_sessions` and
`audit_events`. Unique issuer/subject pairs identify an account; email is not an
identity key. New users are Members. Provider metadata and the Supabase
`authenticated` role cannot grant application administration. Composite foreign keys
prevent a session being attached to another identity's user.

Run the existing explicit migration procedure, then the read-only inventory:

```text
uv run --locked alembic upgrade head
uv run --locked python -m scripts.inventory_legacy_bookings
```

Inventory outputs only aggregate active/cancelled booking counts. Existing room and
booking rows are preserved; no owners are inferred or assigned. Ownership conversion
belongs to the later booking slice. Back up live data before migrations through the
release procedure. Schema migration never runs automatically at application startup.

Compatible application rollback leaves these additive tables in place. Downgrade
`0002` refuses to remove any populated identity table, including audit data, and locks
the tables before checking. Empty synthetic test schemas can be downgraded. Do not
delete identity records to force a live rollback.

## Session lifecycle

The internal `SessionService.establish` accepts tokens only from a trusted account
use case, verifies the JWT and performs a live provider user check before creating
or linking a local account. It requires verified email and an active local user.
Reauthentication revokes the previous opaque session and generates a new random
256-bit value. Later assurance changes must use this same rotation boundary.

Only SHA-256 hashes of opaque tokens are stored. Provider access/refresh tokens are
authenticated-encrypted with Fernet. Browser session cookies are HttpOnly, Secure,
SameSite=Lax, Path=/, without Domain, and use `__Host-roombook_session`. Explicit
loopback HTTP development uses `roombook_session`. Cookie lifetime is not authority;
the database enforces idle/absolute expiry even if the browser retains a cookie.

Every authenticated request validates the stored provider JWT and reads the current
local role/active state. Signatures accept only ES256/P-256 or RS256 with RSA keys of
at least 2,048 bits. Issuer, audience, expiry, subject/session IDs, assurance and
nonanonymous status are checked. The pinned issuer's JWKS cache defaults to five
minutes, has bounded size, throttles unknown-key lookups, and never uses an expired
cache after a failed fetch. User metadata is not proof of email confirmation.

Provider `/user` revalidation is due after five minutes, or sooner during refresh.
Provider-side revocation/ban detection is bounded by that interval and provider
behaviour; it is not immediate. When due, an outage returns 503 without moving the
last successful check forward. Existing validation may be used only inside its
configured interval. Invalid identities revoke the local session.

Refresh begins within 60 seconds of token expiry. A persisted 15-second lease
coordinates processes, and followers wait at most two seconds before returning 503.
Network calls happen outside database transactions. Completed work rechecks local
revocation, active state, token expiry and the lease before persisting tokens. Refresh
must retain the same issuer, subject, provider session and assurance. Expired leases
or uncertain refresh outcomes revoke locally and require a new sign-in; a possibly
consumed rotating refresh token is never retried blindly.

Local logout is immediate and idempotent, independent of provider availability. It
does not sign out other provider devices. The internal user-session revocation hook
supports later protected access changes; those use cases must coordinate role or
suspension changes and revocation in one service-owned transaction. No role-changing
or admin bootstrap endpoint is added here. Audit events allow only internal action,
reason, purpose and count fields, without credentials, email or provider payloads.

## Implemented HTTP contract

| Operation | Behaviour |
| --- | --- |
| `GET /api/v1/auth/session` | Current local user ID/role, assurance, standard purpose, effective expiry and CSRF value; 401 without a valid session, 403 for inactive/recovery-only sessions, 503 if unavailable |
| `POST /api/v1/auth/logout` | Exact configured Origin and matching `X-CSRF-Token` for a supplied session; revoke locally and clear cookie, 204; repeated/no-cookie logout is safe; 403 for failed Origin/CSRF |

Auth responses and errors use `Cache-Control: private, no-store` and
`Referrer-Policy: no-referrer`. Never cache them at a proxy/CDN. Uvicorn access logs
redact the entire auth target. Unexpected account exceptions are converted to safe
500 responses before Uvicorn can log raw tracebacks. Proxy/runtime logging still
needs equivalent redaction when RB-46 introduces one-time email callbacks.

OpenAPI and the generated frontend client contain only implemented routes. CSRF and
cookie contracts are described there, but the frontend does not yet render account
screens or issue login cookies. Account credential rate limits, scanner-safe
confirmation, recovery and exact callback allowlists remain RB-46/RB-48 work.

## Verification and review

Use the normal backend checks and a dedicated PostgreSQL database ending in `_test`.
Tests generate local signing keys and mock only external provider HTTP; application
sessions, migration and concurrency tests use real PostgreSQL. Test dependencies are
injected only inside tests. No runtime authentication bypass is provided. CI must not
use Production identities or require live inbox delivery.

Daniel independently verifies the implementation and controlled Staging account
behaviour. Prattay retains CI/CD ownership; Bhathiya retains runtime, monitoring and
recovery verification. Automated agent review supplements human acceptance. See the
[verification record](RB-45-verification.md) for observed checks and limitations.

Provider references: [Supabase signing keys](https://supabase.com/docs/guides/auth/signing-keys),
[sessions](https://supabase.com/docs/guides/auth/sessions),
[JWT claims](https://supabase.com/docs/guides/auth/jwt-fields),
[PyJWT validation](https://pyjwt.readthedocs.io/en/stable/api.html).

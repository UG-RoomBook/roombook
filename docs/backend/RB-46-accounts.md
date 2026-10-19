# RB-46: Verified member account flows

Implementation owner: Saad. Independent reviewer: Daniel.

RB-46 builds on [RB-45 sessions](RB-45-sessions.md). React calls the same-origin
FastAPI API; FastAPI alone talks to hosted Supabase Auth. Passwords are submitted
over the account API and are never persisted locally. Supabase access and refresh
tokens remain encrypted on the server. A browser receives only an opaque HttpOnly
session cookie and the limited current-session/CSRF response.

## Setup and migration

Install the committed backend lockfile (`uv sync --locked`) and apply additive
migration `0003` using the existing explicit migration procedure. It creates only
`account_attempts`, preserving identity, room and booking records. Application
rollback can leave the table in place. Downgrading `0003` removes rate counters,
so do not use a schema downgrade to evade throttling on a live service.

Supply the protected RB-45 authentication settings, including the exact browser
origin in `ROOMBOOK_AUTH_SITE_URL`. Serve React and `/api/v1/auth/*` from that origin.
Remote environments require HTTPS and Secure cookies. Explicit loopback development
may use `http://127.0.0.1:5173` with the development/test-only insecure-cookie setting.
Do not place provider configuration or encryption keys in Vite variables.

Reuse the separate Staging and Production projects recorded by RB-48. For each
project, keep email confirmation enabled and secure email change enabled. Set
Supabase's Site URL to that environment's exact public origin. Keep its redirect
allowlist narrow and environment-specific; this application never accepts an
arbitrary callback destination. Do not enable implicit fragment-token callbacks.

## Email templates and confirmation

Customize the provider templates to point to the application's server callback:

| Template | Link target |
| --- | --- |
| Confirm signup / resent signup verification | `{{ .SiteURL }}/api/v1/auth/confirm?token_hash={{ .TokenHash }}&type=email` |
| Reset password | `{{ .SiteURL }}/api/v1/auth/confirm?token_hash={{ .TokenHash }}&type=recovery` |
| Change email address | `{{ .SiteURL }}/api/v1/auth/confirm?token_hash={{ .TokenHash }}&type=email_change` |

In HTML template attributes, encode the ampersand as `&amp;`. Keep templates free of
third-party link tracking. Do not use a link that delivers access/refresh tokens in
a URL fragment. Configure the exact callback path under the chosen environment's
origin; hosted-provider template and allowlist changes still require RB-48's
controlled live-mail verification.

A GET displays a confirmation page without consuming the provider token. It sets
a ten-minute encrypted HttpOnly callback cookie and includes a matching CSRF value
in the form. Only an explicit submission verifies the token through the provider's
`POST /verify` operation. Provider rejection, expiry and replay lead to a fixed
clean sign-in URL with a safe error message.

The page uses a nonce-protected script and same-origin, CORS-mode `fetch` for the
submission. This preserves a real Origin header with `Referrer-Policy: no-referrer`;
a native form POST can send `Origin: null`, which the API deliberately rejects.
JavaScript is required for confirmation. No external scripts or assets are loaded.
The script replaces browser history with an allowlisted clean account URL after
the server redirect. Callback responses are private/no-store and cannot be framed.

Signup and email-change confirmation never silently sign the browser into the
linked account. Sign in explicitly after verification. Secure email change may
require confirmation from both the old and new mailboxes. Recovery alone creates
a session with purpose `recovery`; the ordinary session endpoint rejects it, and
it cannot pass the shared standard-session authorization boundary. It can only
obtain recovery CSRF and submit a new password. Session idle/absolute limits follow
the configured RB-45 policy; provider OTP expiry is independently configured.

Resetting a password or requesting an email change revokes all of that user's
local sessions, including when the upstream result is uncertain. After success,
sign in again. An error may also require a new sign-in or recovery link because
local revocation is deliberately conservative. Provider-wide device revocation
and live provider behaviour remain separate operational checks.

## Implemented API and browser behaviour

| Operation | Contract |
| --- | --- |
| `POST /api/v1/auth/register` | Valid email and 12–128-character password; neutral mail feedback, no automatic session |
| `POST /api/v1/auth/login` | Password sign-in; verified active identity becomes a local Member unless an existing application role says otherwise; rotates prior browser session |
| `POST /api/v1/auth/recover` | Neutral recovery-mail feedback |
| `POST /api/v1/auth/resend` | Neutral signup-verification feedback |
| `GET /api/v1/auth/confirm` | Non-consuming confirmation page for an allowlisted link type |
| `POST /api/v1/auth/confirm` | Same-origin, callback cookie/CSRF-bound server verification, followed by a fixed clean redirect |
| `GET /api/v1/auth/recovery-session` | CSRF only, available exclusively to a recovery session |
| `POST /api/v1/auth/reset-password` | Recovery session, matching Origin and CSRF; set password and revoke local sessions |
| `POST /api/v1/auth/change-email` | Standard session, matching Origin and CSRF; request confirmation and revoke local sessions |

The existing current-session and logout routes remain in use. All state-changing
routes require the exact configured Origin; cross-site Fetch Metadata is rejected.
All account responses use the shared safe error envelope and private/no-store headers.
The generated OpenAPI/client represents these implemented operations.

Account pages provide registration, sign-in, verification resend, recovery,
password reset and email change. Forms keep visible labels, inline errors,
password-manager autocomplete and paste support, and disable duplicate submissions.
The navigation reflects the current session. Successful sign-in, logout, reset
and email change clear private query caches; other tabs receive a random change
notification without identity data. Observed session loss also removes booking
queries. Post-login `next` is restricted to local discovery, review or bookings
paths. Provider credentials and callbacks are never parsed from URL fragments.

## Abuse controls and runtime integration

PostgreSQL shares fixed ten-minute counters across application processes: at most
50 requests per peer/action and 10 per normalized email/action where an email is
provided. HMAC keys avoid storing raw addresses or peer identifiers; counters
older than one hour are removed during later account requests. Limits are an
initial application policy, alongside the provider's own limits.

The application uses `request.client.host`, without parsing arbitrary forwarding
headers itself. Configure the ASGI server to trust forwarding headers only from
the actual reverse proxy, and keep direct backend ingress private. With no trusted
proxy forwarding, users may share the proxy's peer bucket. RB-29/RB-48 must verify
this behaviour under the deployed Compose/Caddy path before qualification.

Redact the entire `/api/v1/auth/*` request target and request bodies at the reverse
proxy, observability and error-reporting layers; the application already redacts
Uvicorn account access targets. Do not capture one-time links, cookies, CSRF values,
passwords or provider payloads in screenshots or logs. Auth responses must bypass
proxy/CDN caches. Apply provider SMTP quotas and deliverability monitoring under RB-48.

## Remaining acceptance

Local implementation evidence is in [RB-46 verification](RB-46-verification.md).
Before Done, Daniel independently reviews the feature and visual states; RB-48
must configure the templates on the actual environment and demonstrate controlled
Staging registration/resend, verification, sign-in/logout, recovery and email
change, including scanner GETs, expired/reused links and delivery failures.
Record environment, source SHA and qualified image digest when available. Use
isolated identities/captured mail in CI, never Production credentials or inboxes.

Admin MFA/access controls remain RB-47. Owned bookings and cancellation remain the
subsequent booking tickets. This feature does not configure AWS, build or promote a
release image, or satisfy the independent Staging/Production gates by itself.

Provider references: [email templates](https://supabase.com/docs/guides/auth/auth-email-templates),
[OTP verification](https://supabase.com/docs/reference/javascript/auth-verifyotp),
[account updates](https://supabase.com/docs/reference/javascript/auth-updateuser).
Browser reference: [Origin and referrer policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy).

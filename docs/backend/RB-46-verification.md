# RB-46 verification — 19 October 2026

Implementation source: `58cd0b6c22030ba0f5cec4a76a599f817c1b1fcc`, on
`feat/RB-46-account-flows`, dependent on RB-45 PR #7 at `4a47a00`.
Owner: Saad. Independent reviewer: Daniel; acceptance remains pending.

## Automated results

Checks used Python 3.12.14, uv 0.13.1, Node 24.19.0 and npm 11.6.2 with committed
lockfiles on Linux. Backend tests used the isolated real PostgreSQL database
`roombook_test`; provider HTTP was synthetic, with real locally signed JWTs and
the production provider adapter/session/database code.

| Check | Observed result |
| --- | --- |
| Ruff lint and format | Passed, 59 files formatted |
| Strict mypy | Passed, 55 source files |
| Backend pytest | **321 passed**, including 27 account cases |
| Backend coverage | 97.01% lines, 86.11% branches; 95.08% combined |
| Alembic drift and OpenAPI implementation/export comparison | Passed at additive migration `0003` |
| Generated frontend API drift | Passed |
| Frontend format, ESLint and TypeScript | Passed |
| Vitest coverage | **117 passed** across 12 files; 96.40% lines, 89.81% branches |
| Vite production build | Passed |

Raw outputs: [backend checks](evidence/RB-46-backend-checks.txt) and
[frontend checks](../frontend/rb46-frontend-checks.txt). The workspace's `./dev
check-api` and `./dev check-web` wrappers ran the commands documented in the root
README, with `--maxWorkers=1` for this workstation's frontend coverage run. Backend
test databases are rejected unless their name ends in `_test`.

Account checks cover neutral registration/recovery/resend responses, verified
Member login, invalid credentials/unverified identities, opaque-cookie privacy,
Origin/CSRF restrictions, non-consuming scanner GETs, provider replay rejection,
restricted recovery, password/email change revocation, separate-user sessions,
shared keyed rate counters, safe errors and rejection of unsupported callback types.
Component checks cover validation, pending states, duplicate-submit prevention,
safe redirects, logout, account switching, cross-tab cache invalidation, expiry,
restricted recovery and error feedback. They do not prove live mail delivery.

## Browser observations

The local in-app browser exercised Vite -> FastAPI -> a separate real PostgreSQL
`roombook_preview_test` database. Only outbound identity HTTP was replaced by the
synthetic provider fixture; locally signed JWT verification and local sessions
were real. The temporary fixture was outside the repository and is not a shipped
runtime authentication bypass. No real mail or live credentials were used.

- Sign-in reached real room discovery and changed navigation to Account.
- The account summary showed the verified Member role; logout returned to sign-in.
- Recovery requests displayed neutral mail feedback.
- A confirmation GET left the token unused. Explicit confirmation reached the
  clean `/account/reset` URL, enabled the reset form only after checking its
  restricted session, and kept ordinary navigation signed out.
- Browser testing found that native form POSTs under `no-referrer` can carry a
  null Origin. The callback now uses a nonce-protected CORS-mode fetch and retains
  strict server Origin checks. The corrected path worked in the browser; regression
  coverage rejects null/missing/foreign Origins even with a valid callback cookie.
- Desktop light/dark forms and a 390 x 844 mobile viewport were inspected. The
  mobile document had no horizontal overflow; the content width was 375 pixels
  after its scrollbar. Tab moved from email to password. Empty submission showed
  inline errors and focused the email input. Independent visual/accessibility
  review and broader device testing remain pending.

Screenshots: [desktop dark](../frontend/screenshots/rb46/signin-dark.jpg),
[desktop light](../frontend/screenshots/rb46/signin-light.jpg), and
[mobile light](../frontend/screenshots/rb46/signin-light-390.jpg).
Password reset and email-change mutation/revocation are verified by the HTTP and
component suites, not by a live mailbox/browser acceptance run.

## Review follow-up and remaining gates

RB-45 review fixed remote-origin insecure-cookie configuration in `dede90c`.
Its GitHub run then exposed an unrelated existing navigation assertion race;
`4a47a00` waits for the timeout URL to settle. The corrected RB-45
[frontend workflow passed](https://github.com/UG-RoomBook/roombook/actions/runs/39236972831).
These implementation reviews do not substitute for Daniel's independent acceptance.

RB-46 remains subject to RB-12/RB-45/RB-48 acceptance. Follow the
[setup guide](RB-46-accounts.md) to configure exact templates and demonstrate
controlled Staging registration/resend, verification, login/logout, recovery and
both-address email change, including expired/reused links, mail scanners, quotas
and delivery failures. CI captured-mail integration remains RB-50. No Staging
deployment, image digest, AWS host or Production qualification is claimed here.

Existing warnings remain visible in the logs: the Starlette/httpx test-client
deprecation, local npm `allow-scripts` setting, dependency annotation messages and
a 671.15 kB frontend bundle warning. None caused a failed check or was suppressed.

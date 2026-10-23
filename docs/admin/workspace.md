# Administrator workspace

Implemented on the feature branch for RB-47 (MFA/admin boundary), RB-52 (rooms), RB-53 (schedules) and RB-55 (administration). This document is the implementation and handoff record. Live Staging acceptance, first-admin setup and deployment are separate rollout steps; no live user roles, room hours or reservations were changed during development.

## Accepted scope and sequence

1. Establish application-owned administrator access, TOTP step-up, local session revocation, audit and safe retry infrastructure.
2. Build Overview, Rooms, Schedules, Bookings, Users and Activity using the existing RoomBook typography, red/neutral palette, room illustrations and Light/Dark/System controls.
3. Connect actual APIs, preserving existing reservations and historical unowned rows.
4. Test migrations, permissions, concurrency and browser journeys; make these checks gate PRs and the candidate build.
5. Submit the application PR and complete controlled Staging acceptance before considering rollout complete.

The overview shows daily operations: active bookings intersecting today in Melbourne, active rooms/accounts, unconfirmed schedules, the day's agenda and recent audit activity. It does not claim historical utilisation analytics. Counts include active application accounts, including admins. List filters and pagination use the URL. Overview and bookings display the server evaluation time and refresh on focus and every 30 seconds while visible. Date filtering includes cancelled bookings when that status is selected. Errors replace stale data and provide retry; editors keep their original revision and unsaved values until explicitly reloaded.

## Access and MFA

Every `/api/v1/admin` request authenticates a live standard opaque cookie session, requires an active application `Admin`, and requires `aal2` plus a timestamp derived from the signed TOTP authentication method claim. Neither client metadata nor the Supabase JWT's generic `authenticated` role grants application administration. Reads recheck inside a transaction under shared user/session locks. Writes repeat the check inside their transaction. Existing provider revalidation and refresh bounds remain in effect.

`/account/mfa` lets verified signed-in members enroll and verify a TOTP authenticator before promotion. The backend brokers fixed Supabase factor endpoints. Provider access/refresh credentials remain encrypted on the server; the enrollment QR and setup key are shown only for setup and never persisted by the client or recorded in audit. A successful verification rotates the opaque cookie, requires the original session to still be live and owned by the same user, and revokes other local sessions. Refreshing a token never renews `mfa_verified_at`.

Role/status changes and verified-factor removal require TOTP verification within ten minutes. The access-change dialog keeps the proposed values during step-up and requires another explicit save. Admins cannot remove their last verified TOTP factor. Removing a factor revokes local sessions even when the provider's removal response is uncertain. Verification and management use database-backed rate limits. Password managers/pasting and normal keyboard navigation remain available.

A shared advisory lock serializes role/status changes and first-admin bootstrap; user rows are locked in stable order. Demotion/suspension revokes local sessions in the same transaction as the change and audit. The last active administrator cannot be demoted or suspended. Suspension leaves bookings intact. Private admin responses are `private, no-store`; account change, logout, expiry and access loss clear private query data.

## Management behavior

- **Rooms:** create inactive with unconfirmed hours; edit name/location/capacity/active state. Confirm actual hours before activation. There is no delete action.
- **Schedules:** whole-document revision-checked updates of multiple weekly windows, date overrides and temporary closures. A date override replaces the entire local day; zero windows means closed. The shared Melbourne/DST policy remains authoritative. Each change requires a reason and an impact preview.
- **Bookings:** filter by room, date, status, room/member text or booking ID. Detail shows ownership, interval and status. Administrators can cancel upcoming or ongoing bookings with an explicit reason; completed bookings remain unchanged. Cancellation releases availability. Legacy bookings are labelled and retained.
- **Users:** search cached verified email or application ID, inspect metadata freshness, change Member/Admin role and active/suspended status. There are no provider account scans, invitations, bulk edits or deletions.
- **Activity:** filter by action, actor or target; inspect actor/time/reason and allowlisted before/after data. Credentials, OTPs, setup secrets and provider payloads never enter audit.

Both preview and save use the existing calendar policy. Save takes the same room lock as booking creation and checks every ongoing/future active booking again. A booking made after a clean preview can still block the save. No room/schedule operation automatically cancels reservations. The operator `set_room_hours` script now advances the same room revision, so an open editor cannot silently overwrite its change.

## API and storage

- `/api/v1/admin/overview`
- `/api/v1/admin/rooms` and `/{room_id}`
- `/api/v1/admin/rooms/{room_id}/schedule` and `/impact`
- `/api/v1/admin/bookings` and `/{booking_id}` and `/{booking_id}/cancel`
- `/api/v1/admin/users` and `/{user_id}`
- `/api/v1/admin/activity`
- `/api/v1/auth/mfa`, `/enroll`, `/verify`, `/{factor_id}/remove`

List pages default to 20 and cap at 100 with stable ordering. Admin writes require the exact Origin and CSRF token; mutations also require a UUID `Idempotency-Key`. Successful room creation, updates, schedule changes, cancellation and access changes store a durable actor/key/payload/result receipt atomically with the change and audit. Replaying a key returns the original result; using that key for another payload is rejected. Authorization is checked even for replay.

The client retains the same key during uncertain responses and disables editing until the result is recovered. It also stores a digest-to-key mapping in tab storage, scoped to the actor, so re-entering an identical operation after refresh can recover its result. Form contents, email addresses and reasons are not stored there. Browsers that disable tab storage retain in-memory retry protection. An operator can investigate audit/receipt history when a self-demotion prevents the caller from replaying a result.

Migration `0006` adds room/user revisions, a verified-email display cache, its checked time, session MFA time and `admin_requests`. Existing IDs, bookings, calendar rules and roles are preserved. Old sessions have no MFA timestamp and must verify an authenticator before admin access. Downgrade refuses to delete populated admin receipt history. Application rollback should keep the additive schema; do not delete receipts to force a downgrade.

OpenAPI and the generated TypeScript SDK describe the implemented endpoints. No booking-create API change, mail transport change or new production secret is introduced. Supabase supplies identity/TOTP; the existing SendGrid SMTP/email integration remains as configured.

## First administrator and recovery

Use the normal environment's protected application configuration. Enable Supabase TOTP enrollment/verification in that environment if it is disabled. A candidate administrator must register, verify their email, sign in, visit `/account/mfa` and verify an authenticator. Within ten minutes an authorized operator runs:

```sh
cd backend
uv run --locked python -m scripts.bootstrap_admin \
  --environment staging \
  --issuer https://PROJECT.supabase.co/auth/v1 \
  --subject EXACT_SUPABASE_USER_UUID \
  --operator OPERATOR_IDENTIFIER \
  --reason 'Initial RoomBook administrator setup'
```

The environment and issuer must exactly match the configured application. Resolve the subject in the correct Supabase project; email alone is not accepted. The command requires an active verified local account with recent completed MFA, refuses while an active admin already exists, records the operator/reason/environment, promotes only the exact mapped user and revokes prior sessions. The new admin signs in and verifies MFA again. This command was tested only on isolated local data.

Maintain a second verified admin and a second verified authenticator for recovery. Another admin can restore suspended access or promote a replacement after normal verified registration. If every administrator loses MFA, a privileged identity-provider operator must follow the team's identity verification/recovery procedure, remove the lost factor in the correct provider account and revoke that user's local sessions through the application's internal `SessionService.revoke_user_sessions` hook under the privileged operator procedure. This PR does not automate the provider's identity-verification or factor-reset decision. The recovered user signs in and enrolls/verifies a new factor. Do not bypass MFA, accept a browser-supplied role or alter booking ownership as a recovery shortcut. First-admin bootstrap is intentionally not an override for an existing active admin.

## Rollout checklist

1. Merge only after backend, frontend and both isolated browser workflow gates pass. Candidate build now depends on the admin browser gate as well as existing checks; the image/digest promotion architecture is unchanged.
2. Deploy through the existing migration/candidate pipeline. Verify runtime commit and schema `0006`; keep the prior image for application rollback.
3. In Staging, use controlled accounts to check guest/member denial, admin TOTP, recent step-up, first-admin setup if required and session revocation. Confirm Supabase's real factor settings; the local test provider cannot establish live provider configuration.
4. Confirm real room hours. Exercise create-inactive → confirm hours → activate, an affected-booking preview/rejection, an ongoing/future cancellation with reason, a user access change and its audit record. Use controlled reservations and restore operational settings afterward.
5. Record Staging evidence against RB-47/RB-52/RB-53/RB-55 and obtain the team's rollout acceptance. Do not mark deployed acceptance complete based on local fixtures.

The browser fixture is guarded to a loopback-only database ending `_e2e_test` and refuses populated room data. Its synthetic identity provider and fixture endpoints live only under `backend/tests`, which is excluded from the application image. The CI test never creates bookings or changes users in a deployed environment.

"""Initialize the first administrator using exact identity and recent verified TOTP."""

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text, update

from app.core.config import Settings
from app.db.session import Database
from app.modules.admin.service import ACCESS_LOCK
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession, ExternalIdentity


def bootstrap(
    database: Database,
    *,
    environment: str,
    issuer: str,
    subject: UUID,
    operator: str,
    reason: str,
    idle_seconds: int = 1800,
) -> UUID:
    now = datetime.now(UTC)
    with database.session() as db, db.begin():
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCESS_LOCK})
        if db.scalar(
            select(func.count())
            .select_from(ApplicationUser)
            .where(ApplicationUser.role == "Admin", ApplicationUser.is_active)
        ):
            raise ValueError("An active administrator already exists; use the admin workspace.")
        user = db.scalar(
            select(ApplicationUser)
            .join(ExternalIdentity)
            .where(ExternalIdentity.issuer == issuer, ExternalIdentity.subject == str(subject))
            .with_for_update(of=ApplicationUser)
        )
        if user is None or not user.is_active or not user.verified_email:
            raise ValueError("A verified, active application account is required.")
        recent = db.scalar(
            select(AuthSession.id)
            .join(ExternalIdentity, ExternalIdentity.id == AuthSession.external_identity_id)
            .where(
                AuthSession.user_id == user.id,
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == str(subject),
                AuthSession.aal == "aal2",
                AuthSession.purpose == "standard",
                AuthSession.revoked_at.is_(None),
                AuthSession.mfa_verified_at >= now - timedelta(minutes=10),
                AuthSession.mfa_verified_at <= now,
                AuthSession.last_seen_at > now - timedelta(seconds=idle_seconds),
                AuthSession.absolute_expires_at > now,
            )
        )
        if recent is None:
            raise ValueError("Complete MFA in RoomBook within ten minutes before bootstrapping.")
        user.role = "Admin"
        user.revision += 1
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, refresh_owner=None, refresh_until=None)
        )
        db.add(
            AuditEvent(
                target_id=user.id,
                action="admin.bootstrap",
                occurred_at=now,
                details={"operator": operator, "reason": reason, "environment": environment},
            )
        )
        return user.id


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("environment", "issuer", "subject", "operator", "reason"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.environment != settings.environment or not settings.auth_supabase_url:
        parser.error("The environment must match the configured application environment.")
    if args.issuer != settings.auth_supabase_url.rstrip("/") + "/auth/v1":
        parser.error("The issuer must match the configured identity provider.")
    if not args.operator.strip() or not 1 <= len(args.reason.strip()) <= 500:
        parser.error("Supply an operator identifier and a reason (1–500 characters).")
    database = Database(settings.database_url)
    try:
        user_id = bootstrap(
            database,
            environment=args.environment,
            issuer=args.issuer,
            subject=UUID(args.subject),
            operator=args.operator.strip(),
            reason=args.reason.strip(),
            idle_seconds=settings.auth_idle_seconds,
        )
        print(f"Administrator initialized: {user_id}. Sign in and complete MFA again.")
    except ValueError as error:
        parser.error(str(error))
    finally:
        database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

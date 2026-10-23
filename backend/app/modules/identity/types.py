"""Provider-neutral identity values; credentials never appear in their representations."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class InvalidIdentity(Exception):
    def __init__(self) -> None:
        super().__init__("Identity could not be verified.")


class ProviderUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("Identity provider is unavailable.")


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    issuer: str
    subject: str = field(repr=False)
    session_id: str = field(repr=False)
    email: str | None = field(repr=False)
    email_verified: bool
    aal: str
    expires_at: datetime
    mfa_verified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProviderTokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


class IdentityProvider(Protocol):
    def verify(self, access_token: str) -> VerifiedIdentity: ...

    def refresh(self, refresh_token: str) -> ProviderTokens: ...

    def revalidate(self, access_token: str) -> VerifiedIdentity: ...

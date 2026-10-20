from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ROOMBOOK_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    database_url: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("ROOMBOOK_DATABASE_URL", "DATABASE_URL"),
    )
    environment: str = "development"
    version: str = "0.1.0"
    commit_sha: str = "unknown"
    # Directory holding the built React app; set in the container image only.
    static_dir: Path | None = None
    auth_enabled: bool = False
    auth_supabase_url: str | None = None
    auth_supabase_publishable_key: SecretStr | None = Field(default=None, repr=False)
    auth_token_encryption_key: SecretStr | None = Field(default=None, repr=False)
    auth_site_url: str | None = None
    auth_cookie_secure: bool = True
    auth_idle_seconds: int = Field(default=1800, ge=60, le=43200)
    auth_absolute_seconds: int = Field(default=43200, ge=60, le=604800)
    auth_revalidate_seconds: int = Field(default=300, ge=1, le=300)

    @field_validator("auth_supabase_url", "auth_site_url")
    @classmethod
    def validate_auth_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Use an origin URL without credentials, paths or query parameters")
        try:
            _port = parts.port
        except ValueError as exc:
            raise ValueError("Use a valid origin port") from exc
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        if self.auth_absolute_seconds < self.auth_idle_seconds:
            raise ValueError("Absolute session expiry must not be shorter than idle expiry")
        if not self.auth_enabled:
            return self
        if not all(
            (
                self.auth_supabase_url,
                self.auth_supabase_publishable_key,
                self.auth_token_encryption_key,
                self.auth_site_url,
            )
        ):
            raise ValueError(
                "Enabled authentication requires its provider, site and secret settings"
            )
        assert self.auth_supabase_url is not None
        assert self.auth_site_url is not None
        if urlsplit(self.auth_supabase_url).scheme != "https":
            raise ValueError("The identity provider requires HTTPS")
        development = self.environment in {"development", "test"}
        site = urlsplit(self.auth_site_url)
        if site.scheme != "https" and not (
            development and site.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("The application requires HTTPS outside loopback development")
        if not self.auth_cookie_secure and not (
            development and site.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Insecure session cookies require loopback development or test")
        return self

    @property
    def auth_cookie_name(self) -> str:
        return "__Host-roombook_session" if self.auth_cookie_secure else "roombook_session"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            url = make_url(value)
        except ArgumentError as exc:
            raise ValueError("Use a PostgreSQL URL with the psycopg driver") from exc
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("Use a PostgreSQL URL with the psycopg driver and database name")
        return value

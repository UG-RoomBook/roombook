from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ROOMBOOK_", env_file=".env", extra="ignore", populate_by_name=True
    )

    database_url: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("ROOMBOOK_DATABASE_URL", "DATABASE_URL"),
    )
    environment: str = "development"
    version: str = "0.1.0"
    commit_sha: str = "unknown"

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

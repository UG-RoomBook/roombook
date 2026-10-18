import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings


def enabled_settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "auth_enabled": True,
        "auth_supabase_url": "https://identity.example",
        "auth_supabase_publishable_key": "synthetic-publishable-key",
        "auth_token_encryption_key": Fernet.generate_key().decode(),
        "auth_site_url": "https://roombook.example",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def test_disabled_identity_needs_no_provider_secrets() -> None:
    settings = Settings(_env_file=None, auth_enabled=False)
    assert settings.auth_cookie_secure is True
    assert settings.auth_cookie_name == "__Host-roombook_session"


def test_enabled_identity_requires_all_settings() -> None:
    with pytest.raises(ValidationError, match="requires"):
        Settings(_env_file=None, auth_enabled=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"auth_supabase_url": "http://identity.example"},
        {"auth_site_url": "https://user:password@roombook.example"},
        {"auth_site_url": "https://roombook.example/path"},
        {"auth_site_url": "https://roombook.example?token=secret"},
        {"auth_site_url": "https://roombook.example/#fragment"},
        {"auth_site_url": "https://roombook.example:wrong"},
        {"auth_site_url": "https://roombook.example\n"},
        {"environment": "production", "auth_cookie_secure": False},
        {"environment": "staging", "auth_site_url": "http://localhost"},
        {"auth_site_url": "http://public.example"},
        {"auth_idle_seconds": 1800, "auth_absolute_seconds": 600},
        {"auth_revalidate_seconds": 301},
    ],
)
def test_unsafe_auth_settings_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        enabled_settings(**changes)


def test_explicit_loopback_http_development_is_supported() -> None:
    settings = enabled_settings(
        environment="development", auth_site_url="http://127.0.0.1:5174/", auth_cookie_secure=False
    )
    assert settings.auth_site_url == "http://127.0.0.1:5174"
    assert settings.auth_cookie_name == "roombook_session"


def test_secret_settings_are_not_in_repr() -> None:
    settings = enabled_settings()
    assert "synthetic-publishable-key" not in repr(settings)
    assert settings.auth_token_encryption_key is not None
    assert settings.auth_token_encryption_key.get_secret_value() not in repr(settings)

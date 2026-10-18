import hashlib

import pytest
from cryptography.fernet import Fernet

from app.modules.identity.crypto import TokenCipher
from app.modules.identity.types import InvalidIdentity, ProviderTokens


def test_tokens_are_authenticated_encrypted_and_not_represented() -> None:
    key = Fernet.generate_key().decode("ascii")
    cipher = TokenCipher(key)
    token = "provider-token-value"
    encrypted = cipher.encrypt(token)
    assert token not in encrypted
    assert encrypted != cipher.encrypt(token)
    assert cipher.decrypt(encrypted) == token
    assert key not in repr(cipher)
    assert token not in repr(ProviderTokens(token, "refresh-value"))
    with pytest.raises(InvalidIdentity):
        TokenCipher(Fernet.generate_key().decode("ascii")).decrypt(encrypted)
    with pytest.raises(InvalidIdentity):
        cipher.decrypt(encrypted[:-5] + "wrong")


@pytest.mark.parametrize(
    "value",
    ["", "broken-ciphertext", "é", "x" * 200_001],
    ids=["empty", "corrupt", "non-ascii", "oversized"],
)
def test_invalid_ciphertext_has_a_fixed_safe_error(value: str) -> None:
    cipher = TokenCipher(Fernet.generate_key().decode("ascii"))
    with pytest.raises(InvalidIdentity, match=r"^Identity could not be verified\.$"):
        cipher.decrypt(value)


@pytest.mark.parametrize("key", ["", "invalid", "é", "x" * 32])
def test_invalid_encryption_keys_have_a_fixed_safe_error(key: str) -> None:
    with pytest.raises(ValueError, match=r"^Authentication encryption key is invalid\.$"):
        TokenCipher(key)


def test_csrf_token_is_stable_keyed_and_distinct_from_session_hash() -> None:
    key = Fernet.generate_key().decode("ascii")
    cipher = TokenCipher(key)
    token = "random-opaque-browser-session"
    csrf = cipher.csrf_token(token)
    assert csrf == TokenCipher(key).csrf_token(token)
    assert len(csrf) == 64
    assert csrf != hashlib.sha256(token.encode()).hexdigest()
    assert csrf != cipher.csrf_token("another-session")
    assert csrf != TokenCipher(Fernet.generate_key().decode("ascii")).csrf_token(token)


@pytest.mark.parametrize(
    "value",
    ["", "x" * 100_001, "\ud800"],
    ids=["empty", "oversized", "invalid-unicode"],
)
def test_invalid_plaintext_is_not_encrypted(value: str) -> None:
    with pytest.raises(InvalidIdentity):
        TokenCipher(Fernet.generate_key().decode("ascii")).encrypt(value)

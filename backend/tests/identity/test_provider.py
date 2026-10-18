import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.modules.identity.provider import SupabaseProvider
from app.modules.identity.types import InvalidIdentity, ProviderTokens, ProviderUnavailable

URL = "https://identity.example.test"
ISSUER = URL + "/auth/v1"


@pytest.fixture
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def claims() -> dict[str, Any]:
    now = int(datetime.now(UTC).timestamp())
    return {
        "iss": ISSUER,
        "aud": "authenticated",
        "iat": now - 10,
        "exp": now + 3600,
        "sub": str(uuid4()),
        "session_id": str(uuid4()),
        "email": "member@example.test",
        "role": "authenticated",
        "aal": "aal1",
        "is_anonymous": False,
        "user_metadata": {"role": "Admin", "email_verified": True},
    }


def public_jwk(key: ec.EllipticCurvePrivateKey, kid: str = "first") -> dict[str, Any]:
    return {
        **jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True),
        "kid": kid,
        "alg": "ES256",
        "use": "sig",
    }


def encode(key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], kid: str = "first") -> str:
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


def make_provider(
    handler: Callable[[httpx.Request], httpx.Response], **options: Any
) -> SupabaseProvider:
    return SupabaseProvider(
        URL,
        "test-publishable",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **options,
    )


def test_signature_claims_and_live_confirmation_are_separate(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any]
) -> None:
    token = encode(signing_key, claims)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["apikey"] == "test-publishable"
        if request.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": [public_jwk(signing_key)]})
        assert request.url == URL + "/auth/v1/user"
        assert request.headers["authorization"] == "Bearer " + token
        return httpx.Response(
            200,
            json={
                "id": claims["sub"],
                "email": claims["email"],
                "aud": "authenticated",
                "is_anonymous": False,
                "email_confirmed_at": "2026-01-01T00:00:00Z",
                "user_metadata": {"role": "Admin"},
            },
        )

    provider = make_provider(handler)
    local = provider.verify(token)
    assert local.email_verified is False
    live = provider.revalidate(token)
    assert live == replace(local, email_verified=True)
    assert len(requests) == 2
    assert "member@example.test" not in repr(live)
    assert claims["sub"] not in repr(live)


@pytest.mark.parametrize(
    "missing",
    [
        "iss",
        "aud",
        "exp",
        "iat",
        "sub",
        "role",
        "aal",
        "session_id",
        "email",
        "is_anonymous",
    ],
)
def test_missing_claims_fail_closed(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], missing: str
) -> None:
    claims.pop(missing)
    provider = make_provider(
        lambda _: httpx.Response(200, json={"keys": [public_jwk(signing_key)]})
    )
    with pytest.raises(InvalidIdentity):
        provider.verify(encode(signing_key, claims))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("iss", "https://other.example.test/auth/v1"),
        ("aud", "anon"),
        ("aud", ["authenticated", "other"]),
        ("sub", "not-a-uuid"),
        ("session_id", "not-a-uuid"),
        ("session_id", "00000000-0000-0000-0000-000000000000"),
        ("role", "service_role"),
        ("aal", "aal3"),
        ("is_anonymous", True),
        ("is_anonymous", 0),
        ("email", ""),
        ("email", None),
        ("email", "name\n@example.test"),
        ("exp", 1),
        ("exp", "9999999999"),
        ("exp", 9999999999.0),
        ("iat", 9999999999),
        ("iat", True),
    ],
)
def test_untrusted_claim_values_are_rejected(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], name: str, value: object
) -> None:
    claims[name] = value
    provider = make_provider(
        lambda _: httpx.Response(200, json={"keys": [public_jwk(signing_key)]})
    )
    with pytest.raises(InvalidIdentity):
        provider.verify(encode(signing_key, claims))


def test_wrong_signature_rejected(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any]
) -> None:
    provider = make_provider(
        lambda _: httpx.Response(200, json={"keys": [public_jwk(signing_key)]})
    )
    with pytest.raises(InvalidIdentity):
        provider.verify(encode(ec.generate_private_key(ec.SECP256R1()), claims))


@pytest.mark.parametrize("token", ["", "bad", "x" * 16_385], ids=["empty", "bad", "oversized"])
def test_malformed_tokens_do_not_reach_provider(token: str) -> None:
    def unexpected(_: httpx.Request) -> httpx.Response:
        pytest.fail("Malformed token must not trigger HTTP")

    with pytest.raises(InvalidIdentity):
        make_provider(unexpected).verify(token)


def test_symmetric_algorithm_does_not_reach_provider(claims: dict[str, Any]) -> None:
    def unexpected(_: httpx.Request) -> httpx.Response:
        pytest.fail("Unsupported algorithm must not trigger HTTP")

    token = jwt.encode(
        claims,
        "a-long-enough-test-secret-only-123456789",
        algorithm="HS256",
        headers={"kid": "first"},
    )
    with pytest.raises(InvalidIdentity):
        make_provider(unexpected).verify(token)


def test_rs256_is_supported(claims: dict[str, Any]) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {
        **jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True),
        "kid": "rsa",
        "alg": "RS256",
        "use": "sig",
    }
    provider = make_provider(lambda _: httpx.Response(200, json={"keys": [jwk]}))
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "rsa"})
    assert provider.verify(token).subject == claims["sub"]


def test_unknown_kids_are_throttled_and_rotation_is_bounded(
    signing_key: ec.EllipticCurvePrivateKey,
    claims: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr("app.modules.identity.provider.time.monotonic", lambda: now[0])
    second = ec.generate_private_key(ec.SECP256R1())
    calls = [0]
    keys = [public_jwk(signing_key)]

    def handler(_: httpx.Request) -> httpx.Response:
        calls[0] += 1
        return httpx.Response(200, json={"keys": keys})

    provider = make_provider(handler)
    provider.verify(encode(signing_key, claims))
    for index in range(10):
        with pytest.raises(InvalidIdentity):
            provider.verify(encode(second, claims, f"unknown-{index}"))
    assert calls[0] == 1
    keys.append(public_jwk(second, "second"))
    now[0] += 31
    assert provider.verify(encode(second, claims, "second")).subject == claims["sub"]
    assert calls[0] == 2


def test_expired_cache_never_uses_stale_key_on_outage(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [100.0]
    monkeypatch.setattr("app.modules.identity.provider.time.monotonic", lambda: now[0])
    calls = [0]

    def handler(_: httpx.Request) -> httpx.Response:
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(200, json={"keys": [public_jwk(signing_key)]})
        return httpx.Response(503, text="internal-secret")

    provider = make_provider(handler, jwks_ttl_seconds=1)
    token = encode(signing_key, claims)
    provider.verify(token)
    now[0] += 2
    for _ in range(2):
        with pytest.raises(ProviderUnavailable, match=r"^Identity provider is unavailable\.$"):
            provider.verify(token)
    assert calls[0] == 2


def test_concurrent_verification_fetches_keys_once(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any]
) -> None:
    calls = [0]

    def handler(_: httpx.Request) -> httpx.Response:
        calls[0] += 1
        return httpx.Response(200, json={"keys": [public_jwk(signing_key)]})

    provider = make_provider(handler)
    token = encode(signing_key, claims)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(provider.verify, [token] * 8))
    assert all(result.subject == claims["sub"] for result in results)
    assert calls[0] == 1


@pytest.mark.parametrize("bad", [{}, {"keys": []}, {"keys": ["bad"]}, {"keys": [{}]}])
def test_invalid_jwks_is_unavailable(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], bad: dict[str, object]
) -> None:
    provider = make_provider(lambda _: httpx.Response(200, json=bad))
    with pytest.raises(ProviderUnavailable):
        provider.verify(encode(signing_key, claims))


@pytest.mark.parametrize("field", ["d", "k", "p"])
def test_jwks_rejects_private_key_material(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], field: str
) -> None:
    key = {**public_jwk(signing_key), field: "secret-must-not-be-used"}
    provider = make_provider(lambda _: httpx.Response(200, json={"keys": [key]}))
    with pytest.raises(ProviderUnavailable):
        provider.verify(encode(signing_key, claims))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_revoked_or_invalid_user_response_is_safe(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], status: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": [public_jwk(signing_key)]})
        return httpx.Response(status, json={"message": "provider-sensitive-detail"})

    with pytest.raises(InvalidIdentity, match=r"^Identity could not be verified\.$"):
        make_provider(handler).revalidate(encode(signing_key, claims))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", str(uuid4())),
        ("email", "another@example.test"),
        ("aud", "anon"),
        ("is_anonymous", True),
        ("is_anonymous", None),
        ("email_confirmed_at", "bad"),
        ("email_confirmed_at", "2026-01-01T00:00:00"),
        ("email_confirmed_at", True),
    ],
)
def test_live_user_cannot_disagree_with_jwt_or_claim_false_verification(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any], field: str, value: object
) -> None:
    user = {
        "id": claims["sub"],
        "email": claims["email"],
        "aud": "authenticated",
        "is_anonymous": False,
        "email_confirmed_at": None,
    }
    user[field] = value

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"keys": [public_jwk(signing_key)]}
            if request.url.path.endswith("jwks.json")
            else user,
        )

    with pytest.raises(InvalidIdentity):
        make_provider(handler).revalidate(encode(signing_key, claims))


def test_unverified_live_email_is_never_promoted_by_user_metadata(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"keys": [public_jwk(signing_key)]}
            if request.url.path.endswith("jwks.json")
            else {
                "id": claims["sub"],
                "email": claims["email"],
                "aud": "authenticated",
                "is_anonymous": False,
                "email_confirmed_at": None,
                "user_metadata": {"email_verified": True},
            },
        )

    assert not make_provider(handler).revalidate(encode(signing_key, claims)).email_verified


def test_refresh_request_is_single_explicit_exchange_with_no_user_state(
    signing_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any]
) -> None:
    token = encode(signing_key, claims)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": [public_jwk(signing_key)]})
        assert request.method == "POST"
        assert request.url == URL + "/auth/v1/token?grant_type=refresh_token"
        assert json.loads(request.content) == {"refresh_token": "old-refresh"}
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={"access_token": token, "refresh_token": "new-refresh", "token_type": "bearer"},
        )

    result = make_provider(handler).refresh("old-refresh")
    assert result == ProviderTokens(token, "new-refresh")
    assert repr(result) == "ProviderTokens()"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"access_token": "x", "refresh_token": "y"},
        {"access_token": None, "refresh_token": "y", "token_type": "bearer"},
    ],
)
def test_malformed_refresh_response_fails_closed(response: dict[str, object]) -> None:
    with pytest.raises(ProviderUnavailable):
        make_provider(lambda _: httpx.Response(200, json=response)).refresh("test-refresh")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://attacker.test"}),
        httpx.Response(429, text="quota-secret"),
        httpx.Response(500, text="internal-secret"),
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=["bad"]),
        httpx.Response(200, json={"padding": "x" * 65_537}),
    ],
)
def test_network_responses_are_bounded_and_safe(response: httpx.Response) -> None:
    with pytest.raises(ProviderUnavailable, match=r"^Identity provider is unavailable\.$"):
        make_provider(lambda _: response).refresh("test-refresh")


def test_timeout_is_not_retried_and_does_not_disclose_provider_exception() -> None:
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        raise httpx.ReadTimeout("secret-token-in-error", request=request)

    with pytest.raises(ProviderUnavailable, match=r"^Identity provider is unavailable\.$"):
        make_provider(handler).refresh("test-refresh")
    assert calls[0] == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://identity.example.test",
        "https://user:pass@identity.example.test",
        "https://identity.example.test/path",
        "https://identity.example.test?q=1",
        "https://identity.example.test#fragment",
        "https://identity.example.test/\n",
    ],
)
def test_configuration_rejects_unpinned_origins(url: str) -> None:
    with pytest.raises(ValueError):
        SupabaseProvider(url, "test-publishable")

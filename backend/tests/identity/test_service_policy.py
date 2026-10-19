import pytest

from app.modules.identity.service import InvalidSession, SessionPolicy, hash_token


@pytest.mark.parametrize("value", ["", "short", "x" * 44, "a" * 42 + "!", "é" * 43])
def test_non_server_token_shapes_are_rejected(value: str) -> None:
    with pytest.raises(InvalidSession):
        hash_token(value)


def test_valid_hash_is_stable_and_policy_is_bounded() -> None:
    assert len(hash_token("a" * 43)) == 64
    assert hash_token("a" * 43) == hash_token("a" * 43)
    assert SessionPolicy().revalidate_seconds == 300
    assert SessionPolicy().refresh_wait_seconds == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"idle_seconds": 0},
        {"absolute_seconds": 1},
        {"revalidate_seconds": 301},
        {"revalidate_seconds": 0},
        {"refresh_margin_seconds": -1},
        {"refresh_lease_seconds": 0},
        {"refresh_wait_seconds": 2.1},
        {"refresh_wait_seconds": -1},
    ],
)
def test_invalid_policy_is_rejected(kwargs: dict[str, int | float]) -> None:
    with pytest.raises(ValueError, match="policy is invalid"):
        SessionPolicy(**kwargs)  # type: ignore[arg-type]

"""Tests for the auth primitives (bcrypt byte limit and hash/verify contract)."""

from __future__ import annotations

import pytest

from app.core.security import (
    BCRYPT_MAX_PASSWORD_BYTES,
    hash_password,
    password_too_long_for_bcrypt,
    verify_password,
)


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("", False),
        ("a" * 72, False),  # exactly 72 ASCII bytes
        ("a" * 73, True),  # 73 ASCII bytes
        ("é" * 36, False),  # 36 * 2 = 72 bytes
        ("é" * 37, True),  # 37 * 2 = 74 bytes
        ("💥" * 18, False),  # 18 * 4 = 72 bytes
        ("💥" * 19, True),  # 19 * 4 = 76 bytes
        ("Sup3rSecret!", False),
    ],
)
def test_password_too_long_for_bcrypt(password: str, expected: bool) -> None:
    assert password_too_long_for_bcrypt(password) is expected


def test_bcrypt_limit_constant_is_72_bytes() -> None:
    assert BCRYPT_MAX_PASSWORD_BYTES == 72


def test_hash_and_verify_round_trip() -> None:
    password = "Sup3rSecret!"
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_hash_and_verify_work_at_exactly_72_bytes() -> None:
    password = "a" * BCRYPT_MAX_PASSWORD_BYTES
    hashed = hash_password(password)
    assert verify_password(password, hashed)


def test_verify_returns_false_for_oversized_password() -> None:
    hashed = hash_password("Sup3rSecret!")
    assert verify_password("a" * 73, hashed) is False
    assert verify_password("💥" * 19, hashed) is False


def test_hash_rejects_oversized_password() -> None:
    with pytest.raises(ValueError):
        hash_password("a" * 73)

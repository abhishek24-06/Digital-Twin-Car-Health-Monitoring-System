"""Authentication primitives: bcrypt password hashing and JWT codecs.

No tokens or secrets are stored in the database or emitted to logs; refresh
tokens are persisted only as a SHA-256 hash of the raw value.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt

from app.core.config import Settings

JWT_TYPE_ACCESS = "access"
JWT_TYPE_REFRESH = "refresh"

#: bcrypt's hard input limit is 72 *bytes*, not characters. The Python bindings
#: (bcrypt 5.x) raise ``ValueError`` when this is exceeded, so callers must
#: reject oversized passwords before hashing to avoid a 500.
BCRYPT_MAX_PASSWORD_BYTES = 72


def password_too_long_for_bcrypt(password: str) -> bool:
    """True when the UTF-8 encoding exceeds bcrypt's 72-byte input limit."""
    return len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (72-byte limit enforced upstream)."""
    if password_too_long_for_bcrypt(password):
        raise ValueError(f"password exceeds bcrypt's {BCRYPT_MAX_PASSWORD_BYTES}-byte limit")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish verification; never raises on malformed hash or input.

    Passwords the platform refused to hash are never verified, even though
    bcrypt's own ``checkpw`` would silently truncate them into a false match.
    """
    if password_too_long_for_bcrypt(password):
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(*, user_id: UUID, settings: Settings, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": JWT_TYPE_ACCESS,
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.auth_access_token_minutes),
    }
    return jwt.encode(payload, settings.json_web_token_secret, algorithm=settings.jwt_algorithm)


def generate_refresh_token_value() -> str:
    """Return a fresh refresh-token value (never persisted raw)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token_value(value: str) -> str:
    """Return the SHA-256 hex digest used as the persistent token reference."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def decode_access_token(token: str, settings: Settings) -> dict:
    """Decode and validate an access token; raises jwt.InvalidTokenError."""
    return jwt.decode(
        token,
        settings.json_web_token_secret,
        algorithms=[settings.jwt_algorithm],
    )

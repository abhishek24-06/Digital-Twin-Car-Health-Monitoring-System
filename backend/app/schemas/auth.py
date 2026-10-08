"""Pydantic schemas for the Phase 6 auth API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import password_too_long_for_bcrypt
from app.schemas.user import UserResponse

_BYTE_LIMIT_MESSAGE = "password must not exceed 72 bytes when encoded as UTF-8"


class RegisterRequest(BaseModel):
    """Create a user account. Role and is_active are never client-controlled."""

    email: EmailStr = Field(description="Email used to sign in (case-insensitive)")
    password: str = Field(
        min_length=8,
        max_length=72,
        description="Password (bcrypt has 72-byte limit; 8+ chars required)",
    )
    full_name: str | None = Field(default=None, max_length=120)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("password")
    @classmethod
    def _password_within_bcrypt_bytes(cls, value: str) -> str:
        if password_too_long_for_bcrypt(value):
            raise ValueError(_BYTE_LIMIT_MESSAGE)
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("password")
    @classmethod
    def _password_within_bcrypt_bytes(cls, value: str) -> str:
        if password_too_long_for_bcrypt(value):
            raise ValueError(_BYTE_LIMIT_MESSAGE)
        return value


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(BaseModel):
    """Self-service password change. Requires the current password."""

    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(
        min_length=8,
        max_length=72,
        description="Password (bcrypt has 72-byte limit; 8+ chars required)",
    )

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("current_password", "new_password")
    @classmethod
    def _password_within_bcrypt_bytes(cls, value: str) -> str:
        if password_too_long_for_bcrypt(value):
            raise ValueError(_BYTE_LIMIT_MESSAGE)
        return value


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


__all__ = [
    "ChangePasswordRequest",
    "LoginRequest",
    "LogoutRequest",
    "RefreshRequest",
    "RegisterRequest",
    "TokenResponse",
]

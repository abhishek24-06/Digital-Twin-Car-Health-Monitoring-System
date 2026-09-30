"""Pydantic schemas for the Phase 6 auth API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import UserResponse


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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    model_config = ConfigDict(str_strip_whitespace=True)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


__all__ = [
    "LoginRequest",
    "LogoutRequest",
    "RefreshRequest",
    "RegisterRequest",
    "TokenResponse",
]

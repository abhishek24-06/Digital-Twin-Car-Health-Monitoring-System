"""Pydantic schemas for the Phase 6 user/identity API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: str
    full_name: str | None = None
    is_active: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    """Fields a user may update about themselves."""

    full_name: str | None = Field(default=None, max_length=120)

    model_config = ConfigDict(extra="forbid")


__all__ = ["UserProfileUpdate", "UserResponse"]

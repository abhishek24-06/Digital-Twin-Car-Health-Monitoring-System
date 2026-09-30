"""Phase 6 self-service user endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_user_service
from app.models.user import User
from app.schemas.user import UserProfileUpdate, UserResponse
from app.services.auth_service import UserService

router = APIRouter()


async def _profile(user: User) -> UserResponse:
    return UserResponse.model_validate(user)


@router.get("/users/me", response_model=UserResponse, summary="Get my profile")
async def get_me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return await _profile(user)


@router.patch("/users/me", response_model=UserResponse, summary="Update my profile")
async def patch_me(
    body: UserProfileUpdate,
    user: Annotated[User, Depends(get_current_user)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> UserResponse:
    """Self-service update. Only full_name may be changed here."""
    updated = await users.update_profile(user.id, full_name=body.full_name)
    return await _profile(updated)

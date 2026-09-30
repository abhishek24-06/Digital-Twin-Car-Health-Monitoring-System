"""Phase 6 auth endpoints: register, login, refresh, logout."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.exceptions import AuthenticationError
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_auth_service
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService

router = APIRouter()


def _token_payload(access: str, refresh: str, expires_in: int, user: User) -> dict:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": UserResponse.model_validate(user),
    }


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
    summary="Create a user account",
)
async def register(
    body: RegisterRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """Register a new account. The caller never supplies a role."""
    user = await auth.register(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )
    return UserResponse.model_validate(user).model_dump()


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for a token pair",
)
async def login(
    body: LoginRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """Login. A 401 is returned for a bad email, a bad password, and an
    inactive account alike, so the existence of an email can never be probed."""
    user = await auth.authenticate(email=body.email, password=body.password)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid email or password")
    access, refresh, expires_in = await auth.issue_token_pair(user)
    return _token_payload(access, refresh, expires_in, user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate a refresh token for a fresh token pair",
)
async def refresh(
    body: RefreshRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """Each refresh rotates the token; the previous one is revoked."""
    access, refresh, expires_in, user = await auth.rotate(body.refresh_token)
    return _token_payload(access, refresh, expires_in, user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
async def logout(
    body: LogoutRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    """Revoke the given refresh token. Idempotent: repeating a logout or
    logging out with an unknown token still returns 204."""
    await auth.revoke(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the authenticated user's profile",
)
async def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user

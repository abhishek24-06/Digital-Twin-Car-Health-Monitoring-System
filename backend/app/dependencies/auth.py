"""FastAPI dependencies that resolve the current user from a bearer token.

The database is the single source of truth: the JWT only carries ``sub`` (and
``type``); role/is_active are re-read from the users table on every request so
a role change, deactivation, or deletion takes effect immediately and a stale
token can never grant lifted privileges.
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import JWT_TYPE_ACCESS, decode_access_token
from app.dependencies.database import get_db as get_db
from app.models.user import ROLE_ADMIN, User
from app.repositories.user_repository import UserRepository

_bearer = HTTPBearer(auto_error=False)

CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    credentials: CredentialsDep,
    session: SessionDep,
) -> User:
    """Resolve and return the authenticated user, or raise 401."""
    if credentials is None:
        raise AuthenticationError("Not authenticated")
    if credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authorization scheme must be Bearer")

    settings = get_settings()
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid or expired token") from exc

    if payload.get("type") != JWT_TYPE_ACCESS:
        raise AuthenticationError("Invalid token type")

    sub = payload.get("sub")
    if not sub:
        raise AuthenticationError("Invalid token payload")

    user = await UserRepository(session).get_by_id(sub)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is not active")

    return user


UserDep = Annotated[User, Depends(get_current_user)]


async def require_admin(user: UserDep) -> User:
    """Like get_current_user but requires the admin role (403 otherwise)."""
    if user.role != ROLE_ADMIN:
        raise AuthorizationError("Admin privileges required")
    return user

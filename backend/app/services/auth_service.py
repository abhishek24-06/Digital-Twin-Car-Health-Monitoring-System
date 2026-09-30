"""Phase 6 authentication service: registration, login, token issuance/rotation.

Password hashing (bcrypt) and JWT encoding live in ``app/core/security``.
Refresh tokens are stored only as a SHA-256 hash, rotated on every refresh,
and revoked on logout or reuse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token_value,
    hash_password,
    hash_refresh_token_value,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import ROLE_USER, User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserService:
    """User account management and self-service operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def get_user(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")
        return user

    async def update_profile(self, user_id: UUID, *, full_name: str | None) -> User:
        user = await self.get_user(user_id)
        if full_name is not None:
            user.full_name = full_name.strip() or None
        await self._session.commit()
        return user


class AuthService:
    """Registration, authentication, and token lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None = None,
    ) -> User:
        normalized = normalize_email(email)
        user = User(
            email=normalized,
            password_hash=hash_password(password),
            role=ROLE_USER,  # clients can never self-select a role
            full_name=full_name.strip() if full_name and full_name.strip() else None,
            is_active=True,
        )
        try:
            created = await self._users.create(user)
        except ConflictError:
            raise ConflictError("A user with this email already exists") from None
        await self._session.commit()
        return created

    async def authenticate(self, email: str, password: str) -> User | None:
        """Verify credentials without revealing whether the email exists."""
        user = await self._users.get_by_email(normalize_email(email))
        if user is None:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    async def issue_token_pair(self, user: User) -> tuple[str, str, int]:
        """Return (access_token, refresh_token, access_ttl_seconds)."""
        access_token = self._create_access_token(user)
        refresh_token = generate_refresh_token_value()
        await self._persist_refresh_token(user, refresh_token)
        await self._session.commit()
        return access_token, refresh_token, self._settings.auth_access_token_minutes * 60

    async def rotate(self, refresh_token_value: str) -> tuple[str, str, int, User]:
        """Validate a refresh token and issue a fresh pair (rotation).

        A revoked/expired token is rejected. Reusing an already-revoked token is
        treated as potential theft: every other refresh token for that user is
        revoked as well.
        """
        stored = await self._find_by_value(refresh_token_value)
        if stored is None:
            raise AuthenticationError("Invalid refresh token")
        if stored.revoked_at is not None:
            # Reuse of a previously rotated/revoked token: assume compromise.
            await self._tokens.revoke_all_for_user(stored.user_id)
            await self._session.commit()
            raise AuthenticationError("Refresh token has been revoked")
        now = datetime.now(UTC)
        if stored.expires_at <= now:
            raise AuthenticationError("Refresh token has expired")

        user = await self._users.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is not active")

        await self._tokens.revoke(stored, revoked_at=now)
        access_token = self._create_access_token(user)
        fresh = generate_refresh_token_value()
        await self._persist_refresh_token(user, fresh)
        await self._session.commit()
        return access_token, fresh, self._settings.auth_access_token_minutes * 60, user

    async def revoke(self, refresh_token_value: str) -> None:
        """Revoke a refresh token on logout (idempotent, always 204)."""
        stored = await self._find_by_value(refresh_token_value)
        if stored is not None and stored.revoked_at is None:
            await self._tokens.revoke(stored)
            await self._session.commit()

    def _create_access_token(self, user: User) -> str:
        return create_access_token(user_id=user.id, settings=self._settings)

    async def _persist_refresh_token(self, user: User, value: str) -> None:
        token = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token_value(value),
            expires_at=datetime.now(UTC) + timedelta(days=self._settings.auth_refresh_token_days),
        )
        await self._tokens.create(token)

    async def _find_by_value(self, value: str) -> RefreshToken | None:
        return await self._tokens.get_by_hash(hash_refresh_token_value(value))

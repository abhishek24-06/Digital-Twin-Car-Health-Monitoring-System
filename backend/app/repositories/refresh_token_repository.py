from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    """Data access for refresh tokens (keys handled only as SHA-256 hashes)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, token: RefreshToken) -> RefreshToken:
        self._session.add(token)
        await self._session.flush()
        await self._session.refresh(token)
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return await self._session.scalar(statement)

    async def revoke(self, token: RefreshToken, revoked_at: datetime | None = None) -> None:
        token.revoked_at = revoked_at or datetime.now(UTC)
        await self._session.flush()

    async def revoke_all_for_user(self, user_id) -> None:
        statement = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(statement)
        await self._session.flush()

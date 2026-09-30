from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.user import User


class UserRepository:
    """Data access for the User entity."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        statement = select(User).where(User.id == user_id)
        return await self._session.scalar(statement)

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return await self._session.scalar(statement)

    async def create(self, user: User) -> User:
        try:
            self._session.add(user)
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("A user with this email already exists") from exc
        await self._session.refresh(user)
        return user

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.refresh_token import RefreshToken
    from app.models.vehicle import Vehicle

MAX_EMAIL_LENGTH = 320
MAX_PASSWORD_HASH_LENGTH = 255
MAX_FULL_NAME_LENGTH = 120

ROLE_USER = "user"
ROLE_ADMIN = "admin"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An application account. Under Phase 6, vehicles are owned by users."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(MAX_EMAIL_LENGTH),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(MAX_PASSWORD_HASH_LENGTH), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16),
        default=ROLE_USER,
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(String(MAX_FULL_NAME_LENGTH), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vehicles: Mapped[list[Vehicle]] = relationship(
        back_populates="owner",
        passive_deletes=True,
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'admin')",
            name="ck_users_role",
        ),
    )

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"

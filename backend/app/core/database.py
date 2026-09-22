import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> None:
    """Create the application async engine and session factory once.

    The engine is a process-wide resource shared by all requests. It must
    not be recreated per request.
    """
    global _engine, _session_factory

    if _engine is not None:
        return

    if settings.app_env == "test":
        # The test suite creates/truncates schema per test; a pool only gets in
        # the way, so tests opt out and open a fresh connection each time.
        pool_kwargs: dict = {"poolclass": NullPool}
    else:
        # Conservative pool for PostgreSQL in general and managed databases
        # (e.g. Supabase) in particular: hosting providers enforce connection
        # limits, so the pool is deliberately small and bounded. pool_pre_ping
        # re-validates idle connections, and pool_recycle force-refreshes them
        # before the provider's idle-timeout can reap them.
        pool_kwargs = {
            "pool_size": 5,
            "max_overflow": 5,
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        }

    _engine = create_async_engine(
        settings.database_url,
        echo=settings.is_debug,
        **pool_kwargs,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def get_engine():
    if _engine is None:
        raise RuntimeError("Engine not initialized. Call init_engine() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Session factory not initialized. Call init_engine() first.")
    return _session_factory


async def dispose_engine() -> None:
    """Dispose of the engine pool (used at application shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def check_database_connection() -> bool:
    """Run a lightweight `SELECT 1` health probe. Returns False on failure."""
    if _engine is None:
        return False
    try:
        async with _engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connectivity check failed")
        return False

from app.models.base import Base

__all__ = ["Base"]


def _ensure_registered() -> None:
    # Importing the concrete models registers their tables on Base.metadata,
    # which Alembic and test setup rely on.
    from app.models import (  # noqa: F401
        agent_diagnosis,
        health_snapshot,
        rag,
        refresh_token,
        telemetry,
        user,
        vehicle,
    )


_ensure_registered()

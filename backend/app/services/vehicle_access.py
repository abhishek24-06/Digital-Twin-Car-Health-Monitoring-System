"""Vehicle access control used by services that operate on a scoped vehicle.

Ownership is enforced below the router so an accidentally mis-wired endpoint
can never bypass it: every user-scoped entry point first resolves the vehicle
through this helper. Admin callers may access any vehicle; all other users may
access only vehicles whose ``owner_user_id`` matches their own id. Unknown or
unowned vehicles surface as a 404.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import NotFoundError
from app.models.user import ROLE_ADMIN, User
from app.repositories.vehicle_repository import VehicleRepository


async def ensure_vehicle_access(
    repository: VehicleRepository,
    vehicle_id: UUID,
    user: User,
) -> None:
    """Raise NotFoundError unless ``user`` may access ``vehicle_id``."""
    if user.role == ROLE_ADMIN:
        if await repository.get_by_id(vehicle_id) is None:
            raise NotFoundError("Vehicle")
        return
    if await repository.get_by_id_and_owner(vehicle_id, user.id) is None:
        raise NotFoundError("Vehicle")

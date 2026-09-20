"""Idempotently seed the demo vehicle the simulator publishes for.

The vehicle is created with a fixed UUID that doubles as the default
``SIMULATOR_VEHICLE_ID`` (``11111111-2222-4333-8444-555555555555``) so the
simulator and the database always agree on the vehicle.

Usage: ``python -m scripts.seed_demo_vehicle`` (or ``make seed-demo-vehicle``).
"""

from __future__ import annotations

import asyncio
import sys
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.database import dispose_engine, get_session_factory, init_engine
from app.core.logging import configure_logging
from app.models.vehicle import Vehicle

DEMO_VEHICLE_ID = UUID("11111111-2222-4333-8444-555555555555")
DEMO_VIN = "DEMO-SIM-0001"


async def seed_demo_vehicle() -> str:
    """Create the demo vehicle if absent; return its id."""
    init_engine(get_settings())
    async with get_session_factory()() as session:
        statement = insert(Vehicle).values(
            id=DEMO_VEHICLE_ID,
            vin=DEMO_VIN,
            make="Acme Motors",
            model="Demo Sedan",
            year=2026,
            engine_type="2.0L Petrol",
        )
        statement = statement.on_conflict_do_nothing(index_elements=["id"])
        await session.execute(statement)
        await session.commit()
    await dispose_engine()
    return str(DEMO_VEHICLE_ID)


async def main() -> None:
    configure_logging()
    vehicle_id = await seed_demo_vehicle()
    print(f"Demo vehicle ready: {vehicle_id} (VIN {DEMO_VIN})")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

VIN_MIN_LENGTH = 5
VIN_MAX_LENGTH = 50
YEAR_MIN = 1900
YEAR_MAX = 2100

SOURCE_TYPE_SIMULATOR = "simulator"
SOURCE_TYPE_REAL = "real"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


class VehicleBase(BaseModel):
    vin: str = Field(
        min_length=VIN_MIN_LENGTH,
        max_length=VIN_MAX_LENGTH,
        description="Vehicle Identification Number",
    )
    make: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=YEAR_MIN, le=YEAR_MAX)
    engine_type: str | None = Field(default=None, max_length=100)

    model_config = ConfigDict(extra="forbid")

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("VIN must not be empty")
        if len(value) < VIN_MIN_LENGTH:
            raise ValueError(f"VIN must be at least {VIN_MIN_LENGTH} characters")
        return value.upper()


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    """Mutable vehicle metadata.

    Ownership, lifecycle (status/source_type/simulation_enabled), VIN and the
    security-relevant fields are intentionally not mutable through this schema
    for self-service users; VIN is immutable after creation.
    """

    make: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    year: int | None = Field(default=None, ge=YEAR_MIN, le=YEAR_MAX)
    engine_type: str | None = Field(default=None, max_length=100)

    model_config = ConfigDict(extra="forbid")


class VehicleResponse(VehicleBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    owner_user_id: UUID | None = None
    source_type: str = SOURCE_TYPE_SIMULATOR
    status: str = STATUS_ACTIVE
    simulation_enabled: bool = False

    model_config = ConfigDict(from_attributes=True)

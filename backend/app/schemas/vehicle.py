from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

VIN_MIN_LENGTH = 5
VIN_MAX_LENGTH = 50
YEAR_MIN = 1900
YEAR_MAX = 2100


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
    """Mutable vehicle metadata. The VIN is immutable after creation."""

    make: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    year: int | None = Field(default=None, ge=YEAR_MIN, le=YEAR_MAX)
    engine_type: str | None = Field(default=None, max_length=100)


class VehicleResponse(VehicleBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

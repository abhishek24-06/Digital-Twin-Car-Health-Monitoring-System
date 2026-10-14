from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class HealthDBResponse(BaseModel):
    status: str
    service: str
    database: str


class DeploymentStatusResponse(BaseModel):
    """Read-only deployment verification.

    Reports what the running process *is* (version/build/environment), which
    feature routes it actually exposes, and whether the database's recorded
    Alembic revision matches the build's expected revision. It never applies a
    migration and never exposes a connection string.
    """

    service: str
    app_version: str
    build_id: str
    environment: str
    database_reachable: bool
    expected_schema_revision: str | None = None
    database_schema_revision: str | None = None
    #: True/False when a comparison was possible, None when the build did not
    #: declare an expected revision or the database could not be read.
    migration_in_sync: bool | None = None
    features: dict[str, bool]
    diagnostics: list[str]

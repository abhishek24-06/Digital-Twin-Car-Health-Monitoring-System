class AppError(Exception):
    """Base class for all application-level errors."""


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str = "Resource") -> None:
        self.resource = resource
        super().__init__(f"{resource} not found")


class ConflictError(AppError):
    """Raised when an operation conflicts with existing state (e.g. duplicate VIN)."""

    def __init__(self, detail: str = "Resource already exists") -> None:
        self.detail = detail
        super().__init__(detail)


class DatabaseError(AppError):
    """Raised when an unexpected database error prevents an operation."""


class AuthenticationError(AppError):
    """Raised when a request lacks or carries invalid credentials (401)."""

    def __init__(self, detail: str = "Not authenticated") -> None:
        self.detail = detail
        super().__init__(detail)


class AuthorizationError(AppError):
    """Raised when authenticated user lacks required privilege (403)."""

    def __init__(self, detail: str = "Insufficient permissions") -> None:
        self.detail = detail
        super().__init__(detail)


class RateLimitError(AppError):
    """Raised when a client exceeds an endpoint's rate limit (429)."""

    def __init__(
        self, detail: str = "Rate limit exceeded", *, retry_after_seconds: float = 0.0
    ) -> None:
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)


class SimulationError(AppError):
    """Raised when the simulator control layer cannot run an operation.

    Maps to 502 in the API: a running simulator is an upstream process the
    platform drives, so a failure to start/stop one is a service-level
    failure, not a client error.
    """

    def __init__(self, detail: str = "Simulation operation failed") -> None:
        self.detail = detail
        super().__init__(detail)

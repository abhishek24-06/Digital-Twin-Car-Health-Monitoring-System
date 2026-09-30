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

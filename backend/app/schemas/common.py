from pydantic import BaseModel


class PaginatedResponse[T](BaseModel):
    """Standard paginated list response envelope."""

    items: list[T]
    page: int
    page_size: int
    total: int

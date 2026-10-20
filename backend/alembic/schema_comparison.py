"""Autogenerate comparison policy for Alembic.

Why this exists
---------------
``ix_rag_chunk_embedding`` is an HNSW index on ``rag_chunks.embedding_store``
that is created *only* by a migration (``4f9d3c2b1a8e``), never by the ORM
metadata used by ``create_all``. Because it lives outside ``Base.metadata``,
``alembic check`` reports it as a removed index on every run::

    Detected removed index 'ix_rag_chunk_embedding' on 'rag_chunks'

The index is intentional, so the fix is not to add it to the models (which
would make ``create_all`` emit it too) but to teach the comparison policy to
ignore *exactly* that one index, and nothing else. Any other index, column,
table or constraint difference is still reported.

The callback is deliberately kept in its own module, importing only SQLAlchemy,
so it can be unit-tested without importing the entire application.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index

#: The single migration-managed index that must be invisible to autogenerate.
MIGRATION_MANAGED_INDEX_NAME = "ix_rag_chunk_embedding"
#: The table that index belongs to; both must match for the exemption to apply.
MIGRATION_MANAGED_INDEX_TABLE = "rag_chunks"


def is_migration_managed_index(obj: Any, name: Any) -> bool:
    """Return True only for the exact migration-managed HNSW index.

    Both the index *name* and the owning *table* are checked so an unrelated
    index that happens to share the name on another table is never exempted.
    """
    if not isinstance(obj, Index):
        return False
    if name != MIGRATION_MANAGED_INDEX_NAME:
        return False
    table = getattr(obj, "table", None)
    return getattr(table, "name", None) == MIGRATION_MANAGED_INDEX_TABLE


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Alembic ``include_object`` hook: filter only the exempt index.

    Every other schema object is included, so all genuine drift stays
    detectable.
    """
    if type_ == "index" and is_migration_managed_index(obj, name):
        return False
    return True

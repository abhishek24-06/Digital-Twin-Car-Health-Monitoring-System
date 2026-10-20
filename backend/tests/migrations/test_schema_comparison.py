"""Regression tests for the Alembic autogenerate comparison policy.

The policy exists so that ``ix_rag_chunk_embedding`` -- an HNSW index created
only by a migration, never by ORM metadata -- does not make ``alembic check``
fail with "Detected removed index". These tests exercise the callback directly
against real ``sqlalchemy`` objects (no database connection), and assert that
*only* that exact index is exempted while every other schema difference remains
detectable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, String, Table

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


def _load_policy():
    """Load ``alembic/schema_comparison.py`` without importing the app."""
    module_name = "alembic_schema_comparison_under_test"
    spec = importlib.util.spec_from_file_location(module_name, ALEMBIC_DIR / "schema_comparison.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


policy = _load_policy()


@pytest.fixture()
def metadata() -> MetaData:
    meta = MetaData()
    Table(
        "rag_chunks",
        meta,
        Column("id", Integer, primary_key=True),
        Column("chunk_index", Integer),
        Index("ix_rag_chunk_version", "chunk_index"),
    )
    return meta


def test_exempt_index_is_filtered_from_comparison(metadata: MetaData) -> None:
    """The exact migration-managed index is ignored (reflected, no compare_to)."""
    target = metadata.tables["rag_chunks"]
    index = Index(
        policy.MIGRATION_MANAGED_INDEX_NAME,
        target.c.id,
        # Reflected-only: created by DB, absent from metadata.
    )

    included = policy.include_object(
        index,
        policy.MIGRATION_MANAGED_INDEX_NAME,
        "index",
        True,
        None,
    )

    assert included is False


def test_index_with_same_name_on_other_table_is_not_exempt(metadata: MetaData) -> None:
    """Name collision on a different table must stay detectable."""
    other = Table(
        "telemetry_records",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    index = Index(policy.MIGRATION_MANAGED_INDEX_NAME, other.c.id)

    assert (
        policy.include_object(index, policy.MIGRATION_MANAGED_INDEX_NAME, "index", True, None)
        is True
    )


def test_unrelated_index_is_not_exempt(metadata: MetaData) -> None:
    """A different index on rag_chunks is still compared."""
    target = metadata.tables["rag_chunks"]
    index = Index("ix_rag_chunk_version", target.c.chunk_index)

    assert policy.include_object(index, "ix_rag_chunk_version", "index", True, None) is True


def test_non_index_objects_are_never_exempt(metadata: MetaData) -> None:
    """Tables, columns and constraints are always included."""
    target = metadata.tables["rag_chunks"]

    assert policy.include_object(target, "rag_chunks", "table", True, None) is True
    assert policy.include_object(target.c.id, "id", "column", True, None) is True
    # A column is not an Index, and must not be filtered even if its name
    # coincidentally matches.
    assert (
        policy.include_object(
            Column("ix_rag_chunk_embedding", String),
            policy.MIGRATION_MANAGED_INDEX_NAME,
            "column",
            True,
            None,
        )
        is True
    )

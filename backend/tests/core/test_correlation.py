"""Tests for the shared workflow correlation-id helper."""

from __future__ import annotations

from app.schemas.workflow import new_correlation_id


def test_new_correlation_id_uses_prefix():
    cid = new_correlation_id("sim")
    assert cid.startswith("sim-")
    assert len(cid) > len("sim-")


def test_new_correlation_id_is_unique():
    assert new_correlation_id("sim") != new_correlation_id("sim")


def test_new_correlation_id_is_url_safe():
    cid = new_correlation_id("rag-query")
    assert cid.startswith("rag-query-")
    assert all(ch.isalnum() or ch in "-_" for ch in cid)

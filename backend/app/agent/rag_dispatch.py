"""Deterministic RAG dispatch for the Phase 5 supervisor (no LLM involved).

The supervisor decides *before* any model call whether to consult the
Manufacturer Guidance Tool. The gate is deliberately conservative: when a tool
exists and the user typed something, we offer evidence — the reasoning step is
instructed to ignore it when it is irrelevant, so we never miss material
manufacturer documentation while still degrading cleanly when RAG is disabled
or the tool is absent.
"""

from __future__ import annotations

from app.agent.tools.manufacturer_guidance import ManufacturerGuidanceTool


def should_use_rag(
    *,
    tool: ManufacturerGuidanceTool | None,
    query: str,
) -> bool:
    """Return ``True`` when the supervisor should run the Manufacturer Guidance Tool.

    ``False`` when the tool is not built (RAG disabled by configuration, no
    corpus backend requested) or there is nothing to ask. Everything else —
    vehicle identity, availability, zero-result safety — is resolved inside the
    tool and reflected in its result.
    """
    return tool is not None and bool(query and query.strip())

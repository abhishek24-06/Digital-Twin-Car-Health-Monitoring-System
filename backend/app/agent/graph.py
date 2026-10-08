"""LangGraph workflow for agentic vehicle reasoning (Phase 4 + Phase 5 RAG).

The graph structure is compiled once per provider/tool configuration key and
cached, so requests no longer pay a ``compile()`` cost. Run-scoped dependencies
(tools, LLM service, repository, session) are NOT baked into the compiled graph;
they are supplied per invocation through the LangGraph runtime context
(:class:`AgentGraphContext`), keeping the cached graph safe to share across
concurrent requests and free of any request/user-specific state.

Flow: ``START -> supervisor -> (conditional) -> rag -> reason -> validate ->
persist -> END``. The supervisor gathers Vehicle Health Context and decides
whether to consult the Manufacturer Guidance Tool; RAG evidence alone is enough
to route to the reasoning step even without telemetry context; when neither the
LLM nor RAG is needed the supervisor short-circuits to validate (canned,
grounded reasoning) so the persist path stays uniform.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent.nodes import (
    persist_node,
    rag_node,
    reason_node,
    should_reason,
    should_reason_or_rag,
    supervisor_node,
    validate_node,
)
from app.agent.state import AgentState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from app.agent.llm_service import LLMService
    from app.agent.tools.manufacturer_guidance import ManufacturerGuidanceTool
    from app.agent.tools.vehicle_context import VehicleContextTool
    from app.repositories.agent_diagnosis_repository import AgentDiagnosisRepository

_GRAPH_CACHE_MAXSIZE = 16

_agent_graph_cache_lock = RLock()
_agent_graph_cache: OrderedDict[tuple[Any, ...], CompiledStateGraph] = OrderedDict()


@dataclass(frozen=True, slots=True)
class AgentGraphContext:
    """Per-run dependencies injected into nodes for a single graph invocation.

    A fresh instance is created per request; the cached compiled graph never
    stores these values, so it carries no request-scoped state.
    """

    tool: VehicleContextTool
    rag_tool: ManufacturerGuidanceTool | None
    llm_service: LLMService
    repository: AgentDiagnosisRepository
    session: Any


async def _supervisor_with_context(
    state: AgentState, *, runtime: Runtime[AgentGraphContext]
) -> dict[str, Any]:
    return await supervisor_node(
        state, tool=runtime.context.tool, rag_tool=runtime.context.rag_tool
    )


async def _rag_with_context(
    state: AgentState, *, runtime: Runtime[AgentGraphContext]
) -> dict[str, Any]:
    return await rag_node(state, rag_tool=runtime.context.rag_tool)


async def _reason_with_context(
    state: AgentState, *, runtime: Runtime[AgentGraphContext]
) -> dict[str, Any]:
    return await reason_node(state, llm_service=runtime.context.llm_service)


async def _persist_with_context(
    state: AgentState, *, runtime: Runtime[AgentGraphContext]
) -> dict[str, Any]:
    return await persist_node(
        state,
        repository=runtime.context.repository,
        session=runtime.context.session,
    )


def build_agent_graph(
    *,
    tool: VehicleContextTool,
    llm_service: LLMService,
    repository: AgentDiagnosisRepository,
    session: Any,
    rag_tool: ManufacturerGuidanceTool | None = None,
) -> CompiledStateGraph:
    """Compile the supervisor -> (rag) -> reason -> validate -> persist workflow.

    Nodes read their dependencies from the per-run runtime context instead of
    closures, so the returned graph carries no request-scoped state and may be
    shared across requests. Construction touches none of the passed objects.
    """
    graph = StateGraph(AgentState, context_schema=AgentGraphContext)
    graph.add_node("supervisor", _supervisor_with_context)
    graph.add_node("rag", _rag_with_context)
    graph.add_node("reason", _reason_with_context)
    graph.add_node("validate", validate_node)
    graph.add_node("persist", _persist_with_context)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        should_reason_or_rag,
        {"rag": "rag", "reason": "reason", "validate": "validate"},
    )
    graph.add_conditional_edges(
        "rag",
        should_reason,
        {"reason": "reason", "validate": "validate"},
    )
    graph.add_edge("reason", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def get_cached_agent_graph(
    cache_key: tuple[Any, ...],
    *,
    tool: VehicleContextTool,
    llm_service: LLMService,
    repository: AgentDiagnosisRepository,
    session: Any,
    rag_tool: ManufacturerGuidanceTool | None = None,
) -> CompiledStateGraph:
    """Return the compiled graph cached for the configuration ``cache_key``.

    The key covers the provider/tool configuration; requests with an identical
    configuration reuse one compiled graph. The cache is bounded (LRU): a
    configuration change produces a fresh graph under its new key and stale
    entries are evicted once the cache is at capacity.
    """
    with _agent_graph_cache_lock:
        cached = _agent_graph_cache.get(cache_key)
        if cached is not None:
            _agent_graph_cache.move_to_end(cache_key)
            return cached
    graph = build_agent_graph(
        tool=tool,
        llm_service=llm_service,
        repository=repository,
        session=session,
        rag_tool=rag_tool,
    )
    with _agent_graph_cache_lock:
        _agent_graph_cache[cache_key] = graph
        _agent_graph_cache.move_to_end(cache_key)
        while len(_agent_graph_cache) > _GRAPH_CACHE_MAXSIZE:
            _agent_graph_cache.popitem(last=False)
    return graph


def clear_agent_graph_cache() -> None:
    """Drop all cached compiled graphs (used by tests and configuration reloads)."""
    with _agent_graph_cache_lock:
        _agent_graph_cache.clear()

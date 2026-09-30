"""LangGraph workflow for agentic vehicle reasoning (Phase 4 + Phase 5 RAG).

The graph is built per execution so the nodes receive the request-scoped tools,
LLM service and persistence dependencies via closures.

Flow: ``START -> supervisor -> (conditional) -> rag -> reason -> validate ->
persist -> END``. The supervisor gathers Vehicle Health Context and decides
whether to consult the Manufacturer Guidance Tool; RAG evidence alone is enough
to route to the reasoning step even without telemetry context; when neither the
LLM nor RAG is needed the supervisor short-circuits to validate (canned,
grounded reasoning) so the persist path stays uniform.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

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


def build_agent_graph(
    *,
    tool: VehicleContextTool,
    llm_service: LLMService,
    repository: AgentDiagnosisRepository,
    session: Any,
    rag_tool: ManufacturerGuidanceTool | None = None,
) -> CompiledStateGraph:
    """Compile the supervisor -> (rag) -> reason -> validate -> persist workflow."""
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", partial(supervisor_node, tool=tool, rag_tool=rag_tool))
    graph.add_node("rag", partial(rag_node, rag_tool=rag_tool))
    graph.add_node("reason", partial(reason_node, llm_service=llm_service))
    graph.add_node("validate", validate_node)
    graph.add_node(
        "persist",
        partial(persist_node, repository=repository, session=session),
    )

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

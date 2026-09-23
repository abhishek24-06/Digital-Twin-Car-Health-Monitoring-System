"""LangGraph workflow for agentic vehicle reasoning (Phase 4).

The graph is built per execution so the nodes receive the request-scoped tool,
LLM service and persistence dependencies via closures.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    persist_node,
    reason_node,
    should_reason,
    supervisor_node,
    validate_node,
)
from app.agent.state import AgentState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from app.agent.llm_service import LLMService
    from app.agent.tools.vehicle_context import VehicleContextTool
    from app.repositories.agent_diagnosis_repository import AgentDiagnosisRepository


def build_agent_graph(
    *,
    tool: VehicleContextTool,
    llm_service: LLMService,
    repository: AgentDiagnosisRepository,
    session: Any,
) -> CompiledStateGraph:
    """Compile the supervisor -> reason -> validate -> persist workflow."""
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", partial(supervisor_node, tool=tool))
    graph.add_node("reason", partial(reason_node, llm_service=llm_service))
    graph.add_node("validate", validate_node)
    graph.add_node(
        "persist",
        partial(persist_node, repository=repository, session=session),
    )

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        should_reason,
        {"reason": "reason", "validate": "validate"},
    )
    graph.add_edge("reason", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()

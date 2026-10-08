"""Focused tests for the cached LangGraph agent graph (Phase 5 polish).

Covers the Task 13 contract:
- requests with an identical provider/tool configuration reuse one compiled
  graph (no per-request ``compile()``),
- distinct configurations never share a compiled graph,
- configuration-sensitive invalidation + bounded LRU eviction,
- the shared graph routes per-run dependencies correctly, so concurrent
  requests with different sessions/tools stay isolated.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import (
    _GRAPH_CACHE_MAXSIZE,
    AgentGraphContext,
    get_cached_agent_graph,
)
from app.agent.service import AgentService
from app.agent.state import AgentState


def _stub() -> SimpleNamespace:
    return SimpleNamespace()


@pytest.fixture(autouse=True)
def _isolate_cache() -> None:
    from app.agent.graph import clear_agent_graph_cache

    clear_agent_graph_cache()
    yield
    clear_agent_graph_cache()


@pytest.fixture
def cache_key() -> tuple[object, ...]:
    return ("mock",)


def _get(key: tuple[object, ...], **overrides) -> CompiledStateGraph:
    kwargs = {
        "tool": _stub(),
        "llm_service": _stub(),
        "repository": _stub(),
        "session": _stub(),
        "rag_tool": None,
    }
    kwargs.update(overrides)
    return get_cached_agent_graph(key, **kwargs)


def test_same_configuration_reuses_compiled_graph(cache_key) -> None:
    first = _get(cache_key)
    second = _get(cache_key)
    assert first is second


def test_cache_identity_ignores_request_scoped_dep_instances(cache_key) -> None:
    first = _get(cache_key)
    second = _get(cache_key, tool=_stub(), repository=_stub(), session=_stub())
    assert first is second


def test_distinct_configurations_do_not_reuse_a_graph(cache_key) -> None:
    mock_graph = _get(cache_key)
    other_graph = _get((*cache_key, "openrouter"))
    assert other_graph is not mock_graph

    cached_mock = _get(cache_key)
    assert cached_mock is mock_graph
    cached_other = _get((*cache_key, "openrouter"))
    assert cached_other is other_graph


async def test_configuration_change_selects_fresh_graph(cache_key) -> None:
    before = _get(cache_key)
    changed = _get((*cache_key, "temperature=0.5"))
    assert changed is not before


def test_clear_agent_graph_cache_invalidates(cache_key) -> None:
    first = _get(cache_key)
    from app.agent.graph import clear_agent_graph_cache

    clear_agent_graph_cache()
    second = _get(cache_key)
    assert second is not first


async def test_cache_is_bounded_lru(cache_key) -> None:
    keys = [(*cache_key, i) for i in range(_GRAPH_CACHE_MAXSIZE + 1)]
    graphs = [_get(key) for key in keys]

    first_rebuilt = _get(keys[0])
    assert first_rebuilt is not graphs[0]

    last_reused = _get(keys[-1])
    assert last_reused is graphs[-1]


class _FakeContextResult:
    context = None
    serialized_context = "{}"
    context_note = ""
    severity = "info"
    confidence = 0.0
    context_timestamp = None


class _FakeTool:
    def __init__(self, log: list) -> None:
        self.log = log

    async def get_context(self, vehicle_id):
        self.log.append(("tool", vehicle_id))
        return _FakeContextResult()


class _FakeRepository:
    def __init__(self, log: list, label: str) -> None:
        self.log = log
        self.label = label

    async def create(self, record):
        self.log.append((self.label, record.agent_run_id))
        return SimpleNamespace(id=uuid4())


class _FakeSession:
    def __init__(self, log: list) -> None:
        self.log = log

    async def commit(self) -> None:
        self.log.append(("commit",))


class _FakeLLMService:
    async def invoke_structured(self, messages):
        raise AssertionError("LLM must not be called on the no-context path")


async def test_shared_graph_routes_per_run_dependencies(cache_key) -> None:
    vehicle_id = uuid4()
    graph = _get(cache_key)

    log_a: list = []
    log_b: list = []
    context_a = AgentGraphContext(
        tool=_FakeTool(log_a),
        rag_tool=None,
        llm_service=_FakeLLMService(),
        repository=_FakeRepository(log_a, "repo-A"),
        session=_FakeSession(log_a),
    )
    context_b = AgentGraphContext(
        tool=_FakeTool(log_b),
        rag_tool=None,
        llm_service=_FakeLLMService(),
        repository=_FakeRepository(log_b, "repo-B"),
        session=_FakeSession(log_b),
    )

    def _state(run_id: str) -> AgentState:
        return {
            "agent_run_id": run_id,
            "vehicle_id": vehicle_id,
            "trigger_type": "USER_QUERY",
            "user_query": "How is my car?",
            "execution_metadata": {"rule_ids": []},
            "user_id": None,
        }

    result_a = await graph.ainvoke(_state("run-1"), context=context_a)
    result_b = await graph.ainvoke(_state("run-2"), context=context_b)

    assert result_a["final_response"]["id"]
    assert result_b["final_response"]["id"]

    assert ("tool", vehicle_id) in log_a
    assert ("tool", vehicle_id) in log_b
    assert ("repo-A", "run-1") in log_a
    assert ("repo-B", "run-2") in log_b
    assert ("commit",) in log_a
    assert ("commit",) in log_b
    assert not [entry for entry in log_a if entry[0] == "repo-B"]
    assert not [entry for entry in log_b if entry[0] == "repo-A"]

    assert _get(cache_key) is graph


async def test_service_cache_key_reflects_config_only() -> None:
    session_a, session_b = _stub(), _stub()

    def _service(session, **settings) -> AgentService:
        from app.agent.config import AgentSettings

        return AgentService(
            session,
            settings=AgentSettings(
                llm_primary_provider="mock",
                llm_fallback_provider="",
                llm_max_retries=0,
                **settings,
            ),
        )

    same_a = _service(session_a)
    same_b = _service(session_b)
    assert same_a._graph_cache_key() == same_b._graph_cache_key()

    different = _service(session_a, llm_temperature=0.9)
    assert different._graph_cache_key() != same_a._graph_cache_key()

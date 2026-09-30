"""Pure unit tests for the Phase 5 agent-<->-RAG glue (no DB, no weights)."""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.citations import build_citations_from_sources
from app.agent.nodes import _format_sources, _guidance_payload, _validate_manufacturer
from app.agent.prompts import SYSTEM_PROMPT, build_query_messages
from app.agent.providers.mock import _inject_mock_manufacturer_guidance, _sources_available
from app.agent.rag_dispatch import should_use_rag
from app.agent.schemas import DiagnosisContent
from app.agent.tools.manufacturer_guidance import (
    ManufacturerGuidanceResult,
    ManufacturerGuidanceTool,
)
from app.rag.schemas import RAGGuidanceResult


def _evidence_dict(index: int) -> dict:
    return {
        "index": index,
        "chunk_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "document_version": 1,
        "source_filename": f"manual_{index}.md",
        "title": f"Section {index}",
        "section_title": f"Part {index}",
        "page_start": 1,
        "page_end": 2,
        "scope": "MODEL",
        "dense_score": 0.5,
        "lexical_score": 0.1,
        "hybrid_score": 0.4,
        "rerank_score": 0.9,
        "content": f"The {index} chunk text is grounded manufacturer material.",
    }


class TestRagDispatch:
    def test_no_tool_never_ragged(self) -> None:
        assert should_use_rag(tool=None, query="anything") is False

    def test_empty_query_never_ragged(self) -> None:
        assert should_use_rag(tool=object(), query="   ") is False

    def test_tool_with_query_reaches_rag(self) -> None:
        assert should_use_rag(tool=object(), query="brake noise when cold?") is True


class TestCitations:
    def test_valid_refs_build_citations_with_provenance(self) -> None:
        evidence = [_evidence_dict(1), _evidence_dict(2)]
        citations, warnings = build_citations_from_sources([2], evidence)
        assert warnings == []
        assert len(citations) == 1
        assert citations[0].index == 1
        assert citations[0].source_filename == "manual_2.md"

    def test_out_of_range_ref_dropped_with_warning(self) -> None:
        evidence = [_evidence_dict(1)]
        citations, warnings = build_citations_from_sources([1, 42], evidence)
        assert len(citations) == 1
        assert any("42" in w for w in warnings)

    def test_duplicate_ref_dropped(self) -> None:
        evidence = [_evidence_dict(1), _evidence_dict(2)]
        citations, warnings = build_citations_from_sources([1, 1], evidence)
        assert len(citations) == 1
        assert any("duplicate" in w for w in warnings)

    def test_no_evidence_means_no_citations(self) -> None:
        citations, warnings = build_citations_from_sources([1], [])
        assert citations == []
        assert warnings == []

    def test_no_refs_means_no_citations(self) -> None:
        citations, warnings = build_citations_from_sources([], [_evidence_dict(1)])
        assert citations == []
        assert warnings == []


class TestManufacturerValidation:
    """Negative grounding + citation integrity gate in validate."""

    def _state(self, *, available: bool, evidence: list[dict]) -> dict:
        return {
            "manufacturer_guidance": {
                "available": available,
                "evidence": evidence,
                "guidance": "Grounded guidance.",
                "reason": "hybrid+rerank",
                "scope": {"make": "Toyota", "model": "Camry", "year": 2024},
                "metrics": {"embedding_model": "phase-5-stub"},
            }
        }

    def _content(self, guidance: str = "Grounded guidance.", cited=None) -> DiagnosisContent:
        return DiagnosisContent(
            summary="s", manufacturer_guidance=guidance, cited_sources=cited or []
        )

    def test_evidence_with_valid_ref_keeps_guidance_and_citation(self) -> None:
        content = self._content(cited=[1])
        state = self._state(available=True, evidence=[_evidence_dict(1)])
        warnings: list[str] = []
        guidance, citations, cited, mf_evidence = _validate_manufacturer(content, state, warnings)
        assert guidance == content.manufacturer_guidance
        assert len(citations) == 1
        assert cited == [1]
        assert len(mf_evidence) == 1
        assert warnings == []

    def test_uncited_guidance_is_dropped(self) -> None:
        content = self._content(cited=[])
        state = self._state(available=True, evidence=[_evidence_dict(1)])
        warnings: list[str] = []
        guidance, citations, _, _ = _validate_manufacturer(content, state, warnings)
        assert guidance == ""
        assert citations == []
        assert any("no grounded citation" in w for w in warnings)

    def test_out_of_range_ref_drops_guidance_and_emits_warning(self) -> None:
        content = self._content(cited=[7])
        state = self._state(available=True, evidence=[_evidence_dict(1)])
        warnings: list[str] = []
        guidance, citations, cited, _ = _validate_manufacturer(content, state, warnings)
        assert guidance == ""
        assert citations == []
        assert cited == []
        assert any("7" in w for w in warnings)

    def test_no_evidence_drops_everything(self) -> None:
        """Negative grounding: no retrieved evidence -> no manufacturer claims."""
        content = self._content(cited=[1])
        state = self._state(available=False, evidence=[])
        warnings: list[str] = []
        guidance, citations, cited, mf_evidence = _validate_manufacturer(content, state, warnings)
        assert guidance == ""
        assert citations == []
        assert cited == []
        assert mf_evidence == []
        assert any("no RAG evidence was retrieved" in w for w in warnings)


class TestToolShaping:
    def _tool(self, session, repo, rag) -> ManufacturerGuidanceTool:
        return ManufacturerGuidanceTool(rag, repo, settings=None, session=session)  # type: ignore[arg-type]

    async def test_vehicle_scoped_result(self) -> None:
        result = RAGGuidanceResult(
            query="q",
            vehicle_scope={"make": "Toyota", "model": "Camry", "year": 2024},
            guidance="[1] excerpt",
            citations=[],
            evidence=[],
            available=True,
            reason="hybrid",
        )

        class _Rag:
            rag_enabled = True

            async def search(self, conn, query, vehicle_scope=None):
                return result

        class _Vehicle:
            make = "Toyota"
            model = "Camry"
            year = 2024
            engine_type = "2.5L Petrol"

        class _Repo:
            async def get_by_id(self, vehicle_id):
                return _Vehicle()

        class _Conn:
            pass

        class _Session:
            async def connection(self):
                return _Conn()

        tool = self._tool(_Session(), _Repo(), _Rag())
        out = await tool.get_guidance(uuid4(), "coolant?")
        assert out.available is True
        assert out.scope is not None and out.scope.make == "Toyota"
        assert out.guidance == "[1] excerpt"

    async def test_missing_vehicle_unavailable(self) -> None:
        class _Repo:
            async def get_by_id(self, vehicle_id):
                return None

        class _Rag:
            rag_enabled = True

            async def search(self, conn, query, vehicle_scope=None):
                raise AssertionError("must not search without a vehicle")

        tool = self._tool(None, _Repo(), _Rag())  # type: ignore[arg-type]
        out = await tool.get_guidance(uuid4(), "q")
        assert out.available is False
        assert out.reason == "no-vehicle"

    async def test_retrieval_error_degrades(self) -> None:
        class _Vehicle:
            make = "Toyota"
            model = "Camry"
            year = 2024
            engine_type = None

        class _Repo:
            async def get_by_id(self, vehicle_id):
                return _Vehicle()

        class _Rag:
            rag_enabled = True

            async def search(self, conn, query, vehicle_scope=None):
                raise RuntimeError("pgvector unavailable")

        class _Session:
            async def connection(self):
                raise RuntimeError("session broken")

        tool = self._tool(_Session(), _Repo(), _Rag())
        out = await tool.get_guidance(uuid4(), "q")
        assert out.available is False
        assert out.reason == "retrieval-error"


class TestMessagesAndMock:
    def test_prompt_includes_guidance_section(self) -> None:
        messages = build_query_messages(
            context_json="",
            user_query="coolant?",
            manufacturer_guidance="[1] check coolant level",
            manufacturer_sources="1. Cooling System (pages 1-2)",
        )
        assert messages[0] is not None
        assert "cited_sources" in SYSTEM_PROMPT
        human = messages[-1].content
        assert isinstance(human, str)
        assert "Manufacturer guidance" in human
        assert "Sources:" in human
        assert "1. Cooling System" in human

    def test_prompt_without_guidance_stays_lean(self) -> None:
        messages = build_query_messages(
            context_json='{"health_status": "ok"}',
            user_query="coolant?",
        )
        human = messages[-1].content
        assert isinstance(human, str)
        assert "Manufacturer guidance" not in human
        assert "Vehicle Health Context" in human

    def test_sources_available_counting(self) -> None:
        messages = [SystemMessage(content="x"), HumanMessage(content="Sources:\n1. A\n2. B\n3. C")]
        assert _sources_available(messages) == 3

    def test_mock_injects_guidance_only_with_sources(self) -> None:
        payload: dict = {}
        _inject_mock_manufacturer_guidance(payload, 0)
        assert payload["cited_sources"] == []
        assert payload["manufacturer_guidance"] == ""

        payload = {}
        _inject_mock_manufacturer_guidance(payload, 2)
        assert payload["cited_sources"] == [1]
        assert payload["manufacturer_guidance"]


class TestGuidancePayloadAndSources:
    def test_guidance_payload_is_json_serializable(self) -> None:
        result = ManufacturerGuidanceResult(
            vehicle_id=uuid4(),
            scope=None,
            guidance="g",
            citations=[],
            evidence=[_evidence_dict(1)],
            available=True,
            reason="hybrid",
        )
        payload = _guidance_payload(result)
        assert payload["available"] is True
        assert payload["evidence"][0]["index"] == 1
        assert "vehicle_id" in payload and "metrics" in payload

    def test_format_sources_builds_numbered_list(self) -> None:
        lines = _format_sources([_evidence_dict(2), _evidence_dict(1)])
        assert lines == "2. Section 2 (Part 2), pages 1-2\n1. Section 1 (Part 1), pages 1-2"

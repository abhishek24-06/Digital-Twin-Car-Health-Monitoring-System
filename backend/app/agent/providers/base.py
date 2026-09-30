"""Base contract shared by every LLM provider adapter (Phase 4).

Structured output: real providers route every completion through
``chat_model.with_structured_output(DiagnosisContent, ...)`` instead of asking
the model for free-form JSON text. The method is ``function_calling`` — the
structured-output mechanism supported by essentially every OpenAI-compatible
endpoint (OpenRouter, Groq): the schema is attached as a forced tool call, the
model must emit the diagnosis as tool-call arguments, and LangChain validates
those arguments against :class:`DiagnosisContent` before returning. Parse
failures are surfaced through ``include_raw=True`` and normalized into a
controlled :class:`StructuredOutputError` here. The canonical JSON written back
into ``ProviderCallResult.content`` therefore always parses as a full
``DiagnosisContent`` document before the downstream ``extract_json_object``
defensive layer and the validate/ground/persist nodes ever see it.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.agent.config import AgentSettings
from app.agent.errors import StructuredOutputError
from app.agent.schemas import DiagnosisContent

#: Method passed to ``with_structured_output``. ``function_calling`` forces the
#: provider to emit the diagnosis as a JSON tool call, which is the structured
#: output mechanism supported by virtually every OpenAI-compatible model on
#: OpenRouter and Groq; providers that cannot honor it surface a bad-request
#: error that keeps mapping to the existing provider bad-request/configuration
#: path instead of silently degrading to free-form text.
STRUCTURED_OUTPUT_METHOD = "function_calling"

_KEY_LIKE_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}"
    r"|[A-Za-z0-9_-]{40,}"
    r"|(?:api[_-]?key|secret|token|password|bearer)[\s=:'\"]*[A-Za-z0-9_.-]{6,})"
)


@dataclass(slots=True)
class ProviderCallResult:
    """Normalized success payload for a single provider invocation."""

    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class LLMProvider(ABC):
    """Common adapter contract for every supported LLM provider."""

    provider_name: str = ""
    structured_output_method: str = STRUCTURED_OUTPUT_METHOD

    def __init__(self, settings: AgentSettings) -> None:
        self._settings = settings

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The resolved model identifier used for requests."""

    @abstractmethod
    def _build_chat_model(self) -> BaseChatModel:
        """Construct the provider chat model (no network happens here)."""

    def get_chat_model(self) -> BaseChatModel:
        return self._build_chat_model()

    def _structured_model(self, chat_model: BaseChatModel):
        """Wrap a chat model so it must emit the ``DiagnosisContent`` schema."""
        return chat_model.with_structured_output(
            DiagnosisContent,
            method=self.structured_output_method,
            include_raw=True,
        )

    async def invoke(self, messages: list[BaseMessage]) -> ProviderCallResult:
        """Run one structured chat completion and normalize the result."""
        model = self._structured_model(self.get_chat_model())
        started = time.perf_counter()
        response = await model.ainvoke(messages)
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            content = _normalize_structured_response(response)
        except StructuredOutputError as exc:
            exc.provider = self.provider_name
            exc.model = self.model_name
            raise
        raw = response.get("raw") if isinstance(response, dict) else None
        usage = getattr(raw, "usage_metadata", None)
        return ProviderCallResult(
            content=content,
            input_tokens=_count_tokens(
                usage.get("input_tokens") if isinstance(usage, dict) else None
            ),
            output_tokens=_count_tokens(
                usage.get("output_tokens") if isinstance(usage, dict) else None
            ),
            latency_ms=latency_ms,
        )


def _normalize_structured_response(response: Any) -> str:
    """Convert an ``with_structured_output(..., include_raw=True)`` result to
    canonical ``DiagnosisContent`` JSON or raise a controlled error."""
    if not isinstance(response, dict):
        raise StructuredOutputError("Structured provider returned an unexpected payload")

    parsing_error = response.get("parsing_error")
    parsed = response.get("parsed")
    if parsing_error is None and parsed is not None:
        return _canonical_json(_as_diagnosis_content(parsed))

    # LangChain's parser rejected the tool call (missing/invalid arguments).
    # Accept the raw message text ONLY when it is itself a valid, complete
    # DiagnosisContent document — this tolerates OpenAI-compatible endpoints
    # whose "parsed" plumbing differs without ever weakening schema validation.
    raw = response.get("raw")
    text = _response_text(getattr(raw, "content", None))
    try:
        content = DiagnosisContent.model_validate_json(text)
    except Exception as exc:  # noqa: BLE001
        detail = _validation_failure_detail(exc, parsing_error, raw)
        raise StructuredOutputError(
            "Structured model output failed schema validation" + (f": {detail}" if detail else "")
        ) from exc
    return _canonical_json(content)


def _as_diagnosis_content(parsed: Any) -> DiagnosisContent:
    try:
        if isinstance(parsed, DiagnosisContent):
            return parsed
        if isinstance(parsed, BaseModel):
            return DiagnosisContent.model_validate(parsed.model_dump(mode="json"))
        if isinstance(parsed, dict):
            return DiagnosisContent.model_validate(parsed)
    except Exception as exc:  # noqa: BLE001
        detail = _safe_error_text(exc)
        raise StructuredOutputError(
            "Structured model output failed schema validation" + (f": {detail}" if detail else "")
        ) from exc
    raise StructuredOutputError("Structured provider returned an unexpected parsed value")


def _validation_failure_detail(exc: Exception, parsing_error: Any, raw: Any) -> str:
    """Compose a sanitized, useful description of why validation failed.

    Prefers the actual validation exception over the parser's generic error and
    flags truncated completions (finish_reason='length') so the operator can
    distinguish a cut-off response from a genuine schema violation. Everything
    is redacted and bounded before it becomes part of the error message.
    """
    parts: list[str] = []
    if _looks_truncated(raw):
        parts.append("model output was truncated (finish_reason='length'); raise llm_max_tokens")
    own = _safe_error_text(exc)
    if own:
        parts.append(own)
    parser = _safe_error_text(parsing_error)
    if parser and parser not in parts:
        parts.append(parser)
    return " ; ".join(parts)


def _looks_truncated(raw: Any) -> bool:
    metadata = getattr(raw, "response_metadata", None) or {}
    return metadata.get("finish_reason") == "length" or metadata.get("stop_reason") == "length"


def _canonical_json(content: DiagnosisContent) -> str:
    return json.dumps(content.model_dump(mode="json"), ensure_ascii=False)


def _safe_error_text(exc: Any) -> str:
    """Trim and sanitize a parse error so diagnostics never leak secrets."""
    if exc is None:
        return ""
    try:
        text = str(exc).strip()
    except Exception:
        return ""
    text = _KEY_LIKE_RE.sub("***", text.replace("\n", " "))
    return text[:300] if len(text) > 300 else text


def _response_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def _count_tokens(value: Any) -> int:
    """Extract a scalar token count from langchain usage metadata."""
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        for key in ("total_tokens", "prompt_tokens", "completion_tokens"):
            scalar = value.get(key)
            if isinstance(scalar, int):
                return scalar
    return 0

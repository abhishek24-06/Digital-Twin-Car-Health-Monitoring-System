"""Phase 5 document parsers.

``plain_text`` handles UTF-8 text/Markdown dumps; ``docling`` is the production
path for PDF/DOCX/office files. ``get_parser_for`` routes by extension and never
silently downgrades a production PDF to plain text.
"""

from __future__ import annotations

from app.rag.parser.base import ParsedSection, ParseResult, RAGParseError
from app.rag.parser.docling import (
    DOCLING_EXTENSIONS,
    PLAIN_TEXT_EXTENSIONS,
    DoclingParser,
    get_parser_for,
)
from app.rag.parser.plain_text import PlainTextParser


def supported_extensions() -> frozenset[str]:
    """The extensions the parser registry can actually handle.

    Derived at runtime from the registry constants (``DOCLING_EXTENSIONS`` +
    ``PLAIN_TEXT_EXTENSIONS``) so the upload validation layer never maintains a
    second, hardcoded extension list — the registry stays the source of truth.
    """
    return frozenset(DOCLING_EXTENSIONS | PLAIN_TEXT_EXTENSIONS)


__all__ = [
    "DOCLING_EXTENSIONS",
    "PLAIN_TEXT_EXTENSIONS",
    "DoclingParser",
    "ParseResult",
    "ParsedSection",
    "PlainTextParser",
    "RAGParseError",
    "get_parser_for",
    "supported_extensions",
]

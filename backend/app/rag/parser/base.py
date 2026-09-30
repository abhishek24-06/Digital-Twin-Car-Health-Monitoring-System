"""Parser contracts for Phase 5 ingestion.

A parser turns a source file into a *normalised intermediate* — canonical
plain text plus the structure (headings/sections) plus page provenance — that
the chunker then turns into vectorised chunks. Every parser records its own
name + version so a :class:`~app.models.rag.RagDocumentVersion` can state
exactly which loader produced it (provenance is the point).

This module is import-light: no model weights, no Docling, no database.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.rag.errors import RAGParseError
from app.rag.schemas import VehicleScope

# Re-exported here because the sub-parsers import the error from ``base``.
__all__ = [
    "ParseResult",
    "ParsedSection",
    "BaseParser",
    "RAGParseError",
    "make_plain_result",
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_BLANK_RE = re.compile(r"[ \t]+")

# Canonical text convention: heading lines are emitted as Markdown ``# …``
# lines (same convention for plain-text and Docling paths) so the structure
# chunker consumes one uniform intermediate.
_HEADING_MARK_RE = re.compile(r"^(#{1,6})\s+")


@dataclass
class ParsedSection:
    """One structure unit of a parsed document.

    ``heading`` is the title (text after the ``#``), ``heading_depth`` the
    number of ``#`` characters, ``heading_path`` the *full* breadcrumb
    (e.g. ``["Maintenance", "Brakes"]``), ``page_start``/``page_end`` are
    1-based, and ``char_start``/``char_end`` are offsets inside the canonical
    plain-text dump (filled by parsers that track byte spans).
    """

    heading: str
    heading_depth: int
    heading_path: list[str]
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    body: str = ""
    scope: VehicleScope | None = None


@dataclass
class ParseResult:
    """Normalised output of one parser run (immutable by convention)."""

    text: str
    sections: list[ParsedSection] = field(default_factory=list)
    pages: list[tuple[int, str]] = field(default_factory=list)
    scope: VehicleScope | None = None
    content_hash: str = ""
    page_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def sha256_hex(text: str) -> str:
    """Stable content hash of canonical text (hex, lowercase)."""
    return sha256(text.encode("utf-8")).hexdigest()


def sections_from_text(text: str) -> list[ParsedSection]:
    """Derive ``ParsedSection`` list from canonical ``#``-heading text.

    Heading lines cut the hierarchy; non-heading text between a heading and the
    next becomes that section's body. ``heading_path`` is the full breadcrumb
    computed with a heading stack, so nested sections get accurate ancestry.
    ``char_start``/``char_end`` are byte offsets into ``text``.
    """
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    marks: list[tuple[int, str, str]] = []  # (line_index, depth_hashes, title)
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            marks.append((i, m.group(1), m.group(2).strip()))

    if not marks:
        return []

    sections: list[ParsedSection] = []
    stack: list[str] = []
    offsets: list[int] = []
    o = 0
    for ln in lines:
        offsets.append(o)
        o += len(ln)

    for k, (idx, hashes, title) in enumerate(marks):
        end_idx = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        # Trim trailing blank lines from the body for stable hashes.
        body_lines = lines[idx + 1 : end_idx]
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        body = "".join(body_lines).rstrip()

        depth = len(hashes)
        while stack and len(stack) >= depth:
            stack.pop()
        stack.append(title)

        char_start = offsets[idx]
        char_end = (
            offsets[end_idx - 1] + len(lines[end_idx - 1])
            if end_idx - 1 < len(lines)
            else offsets[idx]
        )
        sections.append(
            ParsedSection(
                heading=title,
                heading_depth=depth,
                heading_path=list(stack),
                char_start=char_start,
                char_end=char_end,
                body=body,
            )
        )
    return sections


class BaseParser(ABC):
    """Parsers produce :class:`ParseResult`; they never touch the DB.

    Subclasses set ``name`` and ``version``; :meth:`parse` reads one source
    file from disk and returns its normalised form. Scope derivation happens in
    the ingestion layer, *after* parse time, so a parser stays dump-agnostic.
    """

    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    def parse(self, path: Path) -> ParseResult:
        """Parse ``path`` and return the canonical intermediate."""
        ...

    def pages_from_text(self, text: str, *, per_page: int = 4400) -> list[tuple[int, str]]:
        """Heuristic pages for plain dumps (only when the parser is page-less)."""
        pages: list[tuple[int, str]] = []
        for i in range(0, len(text), per_page):
            pages.append((i // per_page + 1, text[i : i + per_page]))
        return pages


def make_plain_result(
    text: str,
    *,
    title: str = "",
    page_dump: bool = False,
    page_len: int = 4400,
) -> ParseResult:
    """Deterministic plain-text ``ParseResult`` factory (loader + stubs)."""
    pages: list[tuple[int, str]] = []
    if page_dump:
        pages = [(i // page_len + 1, text[i : i + page_len]) for i in range(0, len(text), page_len)]
    sections = sections_from_text(text)
    for sec in sections:
        if sec.char_start is not None and sec.char_end is not None:
            p1 = sec.char_start // page_len + 1
            p2 = max((sec.char_end - 1) // page_len + 1, p1)
            sec.page_start, sec.page_end = p1, p2
    return ParseResult(
        text=text,
        sections=sections,
        pages=pages,
        page_count=len(pages) or (1 if text else 0),
    )

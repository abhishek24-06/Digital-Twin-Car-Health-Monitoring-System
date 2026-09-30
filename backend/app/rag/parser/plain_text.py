"""Plain-text (``.txt``/``.md``) parser: deterministic structural extraction.

Intended input: manufacturer service manual dumps saved as plain text. The
parser:

* strips zero-width / BOM / CRLF noise,
* preserves Markdown-style heading lines (``#``..``###### ``) verbatim in the
  canonical text and derives ``ParsedSection`` hierarchy from them,
* tracks explicit page markers (``----- Page 12 -----``) when present and maps
  them onto section page spans,
* keeps the whole file in the canonical dump (preamble included) so the chunker
  can carve self-contained units.

Never guesses page numbers: page spans stay ``None`` unless real markers exist.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.rag.parser.base import (
    ParseResult,
    RAGParseError,
    sections_from_text,
    sha256_hex,
)

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_PAGE_MARKER_RE = re.compile(r"^\s*-{3,}\s*[Pp]age\s+(\d+)\s*-{3,}\s*$")
_BOM_RE = re.compile(r"^\ufeff")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\u2060\ufeff]")


def _canonicalise(lines: list[str]) -> tuple[list[str], list[tuple[int, int]]]:
    """Return ``(kept_lines, page_boundaries)`` where each boundary is
    ``(char_offset, page_number)`` — the offset of the line *after* the marker.
    """
    kept: list[str] = []
    boundaries: list[tuple[int, int]] = []
    current_page = 1
    for line in lines:
        page_m = _PAGE_MARKER_RE.match(line)
        if page_m:
            current_page = int(page_m.group(1))
            boundaries.append((sum(len(x) for x in kept), current_page))
            continue
        cleaned = _ZERO_WIDTH_RE.sub("", line)
        head_m = _HEADING_RE.match(cleaned)
        if head_m:
            cleaned = f"{'#' * len(head_m.group(1))} {head_m.group(2).rstrip()}\n"
        kept.append(cleaned)
    return kept, boundaries


def parse_plain_text(path: Path) -> ParseResult:
    """Parse a UTF-8 text/markdown dump into a canonical ``ParseResult``."""
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise RAGParseError(f"cannot read {path.name}: {exc}") from exc

    raw = _BOM_RE.sub("", raw)
    kept, boundaries = _canonicalise(raw.splitlines(keepends=True))
    text = "".join(kept)
    sections = sections_from_text(text)

    # Map section char spans onto page markers when they exist.
    if boundaries:
        for sec in sections:
            if sec.char_start is None or sec.char_end is None:
                continue
            pages_inside = [p for o, p in boundaries if sec.char_start <= o < sec.char_end]
            pages_span = [p for o, p in boundaries if o <= sec.char_end and o >= sec.char_start]
            if pages_inside:
                sec.page_start = min(pages_inside)
                sec.page_end = max(pages_inside)
            elif pages_span:
                # Section straddles a marker start; use the boundary page for both.
                sec.page_start = sec.page_end = pages_span[-1]

    page_count = max((p for _, p in boundaries), default=None)
    pages: list[tuple[int, str]] = []
    if boundaries:
        prev = 0
        for offset, no in sorted(boundaries):
            pages.append((no, text[prev:offset]))
            prev = offset
        if prev < len(text):
            page_no = max((no for _, no in boundaries), default=1)
            pages.append((page_no, text[prev:]))

    return ParseResult(
        text=text,
        sections=sections,
        pages=pages,
        content_hash=sha256_hex(text),
        page_count=page_count,
        metadata={"parser": "plain-text"},
    )


class PlainTextParser:
    """Concrete parser facade matching the :class:`BaseParser` contract."""

    name = "plain-text"
    version = "1.1.0"

    def __init__(self, *_: object, **__: object) -> None:
        pass

    def parse(self, path: Path) -> ParseResult:
        return parse_plain_text(path)

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".md", ".text"}

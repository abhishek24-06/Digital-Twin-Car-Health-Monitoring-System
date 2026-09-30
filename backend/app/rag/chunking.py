"""Structure-aware plain-text chunking (pure, deterministic).

Phase 5 chunks *structure*: headings carve the hierarchy, sections stay whole
when they fit, and every produced chunk records its heading path plus char and
page spans so evidence is traceable to the exact source bytes. No I/O, no model
loads, no settings required (caps are optional).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_YEAR_RE = re.compile(r"(19|20)\d{2}")

HEADING_DEPTH = 6

CHUNKING_VERSION = "structural-1.0.0"


@dataclass(frozen=True)
class Chunk:
    """One planned text chunk with full provenance (pre-embedding)."""

    chunk_index: int
    chunk_type: str  # "section" | "continuation" | "preamble"
    title: str
    section_title: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    start_char: int
    end_char: int
    content: str
    metadata: dict = field(default_factory=dict)


def approx_pages(start_char: int, end_char: int, chars_per_page: int = 4400) -> tuple[int, int]:
    """Best-effort page span from char offsets.

    ``chars_per_page`` defaults to ~4400 (plain text, 12pt, single column);
    callers that know real page boundaries pass them directly instead.
    """
    if end_char <= 0:
        return (0, 0)
    p1 = start_char // chars_per_page + 1
    p2 = (end_char - 1) // chars_per_page + 1
    if p2 < p1:
        p2 = p1
    return p1, p2


def chunk_by_structure(
    raw: str,
    size: int = 800,
    overlap: int = 120,
    min_page: int = 1,
    chars_per_page: int = 4400,
) -> list[Chunk]:
    """Heading-aware chunker.

    * Splits ``raw`` on heading lines (``# Title``).
    * Keeps a section's body together when ``len <= size``.
    * Overlong sections become fixed size-``size`` windows with ``overlap``
      overlap; window boundaries never split a heading line.
    * Subsequent windows reuse the section heading path and are marked
      ``chunk_type="continuation"``.
    """
    lines = raw.splitlines(keepends=True)
    if not lines:
        return []

    # Build the section table: heading index -> (depth, title, content_start)
    heading_pos = [(i, _HEADING_RE.match(lines[i])) for i in range(len(lines))]
    headings = [(i, m.group(1), m.group(2).strip()) for i, m in heading_pos if m]

    sections: list[dict] = []  # start, end, depth, title, path(filled later)
    if not headings:
        sections.append({"start": 0, "end": len(lines) - 1, "depth": 0, "title": "", "path": []})
    else:
        # Optional leading preamble (text before the first heading) is the ONLY
        # anonymous segment; body between headings belongs to the heading above.
        first_hi = headings[0][0]
        if first_hi > 0:
            sections.append({"start": 0, "end": first_hi - 1, "depth": 0, "title": "", "path": []})
        for k, (hi, depth, title) in enumerate(headings):
            end = headings[k + 1][0] - 1 if k + 1 < len(headings) else len(lines) - 1
            sections.append(
                {"start": hi, "end": end, "depth": len(depth), "title": title, "path": []}
            )

    # Fill heading paths (reuse nearest shallower ancestor's title).
    stack: list[str] = []
    # char offsets of each line (sum of previous line lengths)
    offsets: list[int] = []
    o = 0
    for ln in lines:
        offsets.append(o)
        o += len(ln)

    for sec in sections:
        depth = sec["depth"]
        while stack and len(stack) > depth:
            stack.pop()
        if sec["title"]:
            if stack and len(stack) >= depth:
                stack = stack[: depth - 1]
            stack.append(sec["title"])
        sec["path"] = list(stack)

    # Emit.
    out: list[Chunk] = []
    for sec in sections:
        s_char = offsets[sec["start"]]
        e_line = offsets[sec["end"]] + len(lines[sec["end"]])
        sec_len = e_line - s_char
        heading_path = sec["path"]
        if sec_len <= size:
            content = "".join(lines[sec["start"] : sec["end"] + 1]).rstrip()
            p_start, p_end = approx_pages(s_char, e_line, chars_per_page)
            out.append(
                Chunk(
                    chunk_index=len(out),
                    chunk_type="section",
                    title=sec["title"],
                    section_title=sec["title"],
                    heading_path=heading_path,
                    page_start=p_start,
                    page_end=p_end,
                    start_char=s_char,
                    end_char=e_line,
                    content=content,
                )
            )
            continue
        # Overlong: fixed windows over the body (first line = heading when present).
        start_char = s_char
        if sec["title"]:
            start_char += len(lines[sec["start"]])
        body_start = start_char
        pos = body_start
        idx = 0
        while pos < e_line:
            end = min(pos + size, e_line)
            if end < e_line:
                cut = raw.rfind(" ", pos + size - overlap - 1, end)
                if cut > pos:
                    end = cut
            p_start, p_end = approx_pages(pos, end, chars_per_page)
            out.append(
                Chunk(
                    chunk_index=len(out),
                    chunk_type="continuation" if idx else "section",
                    title=sec["title"] if idx == 0 else "",
                    section_title=sec["title"],
                    heading_path=heading_path,
                    page_start=p_start,
                    page_end=p_end,
                    start_char=pos,
                    end_char=end,
                    content=raw[pos:end].strip(),
                )
            )
            idx += 1
            if end >= e_line:
                break
            pos = end - overlap

    return out

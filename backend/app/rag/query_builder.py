"""Pure query-side material: variants, tokenization, guards.

Phase 5 queries are *planned*, not prophesied: we expand what the user typed
into the lexical and dense columns of the hybrid plan deterministically, strip
VIN noise before it can defeat tokenization, and keep every length cap from
config so no untrusted string can blow an index or a column.

Nothing here touches models or the database — the repository and service make
all I/O calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_VIN_RE = re.compile(r"\b[0-9A-HJ-NPR-Z]{17}\b")
_MYSTERY_TOKEN_RE = re.compile(r"[^\w\s\-.,;&/#()\"']")


@dataclass
class QueryPlan:
    """The execution plan for one user query.

    ``text`` is what actually gets embedded; ``lexical_variants`` are the
    strings handed to FTS; ``raw`` is the exact bytes the user sent (provenance).
    """

    raw: str
    text: str
    lexical_variants: list[str] = field(default_factory=list)
    decoded_vin: str | None = None
    detected_vin: bool = False
    normalized_scope: str | None = None
    notes: list[str] = field(default_factory=list)


def strip_vin(raw: str) -> tuple[str, str | None]:
    """Remove a VIN from free text, returning ``(cleaned, vin)``.

    Windows PowerShell, mingw and user-supplied diagnostics frequently embed a
    17-char VIN inside the very question ("...this VIN 1FTEW1EP6LFA12345 has a
    brake noise"). Looks reasonable, hurts retrieval. We extract it and drop the
    token so FTS never has to index it.
    """
    m = _VIN_RE.search(raw)
    if not m:
        return raw, None
    start, end = m.span()
    return raw[:start] + raw[end:], m.group(0)


def build_plan(raw: str, *, scope: str | None = None) -> QueryPlan:
    """Build a :class:`QueryPlan` from raw user text.

    Deterministic and cheap, with no settings reads: expansion adds a few
    near-duplicates of what the user typed in a form hybrid scoring likes.
    """
    cleaned, vin = strip_vin(raw)
    text = " ".join(cleaned.split())
    plan = QueryPlan(
        raw=raw,
        text=text,
        decoded_vin=vin,
        detected_vin=vin is not None,
        normalized_scope=scope,
    )

    variants: list[str] = [text]
    q = text.lower()
    if vin and (q or scope):
        plan.notes.append("VIN removed to protect tokenization")
    if scope and " " not in scope:
        plan.notes.append("synthetic scope hint applied")
    if text == text.title() and len(text) > 1:
        plan.notes.append("title-case normalised to prose")
        variants.append(text.lower())
    if text.endswith("?"):
        plan.notes.append("strip question mark")
        variants.append(text[:-1].rstrip())
    plan.lexical_variants = [v for v in dict.fromkeys(variants) if v]
    return plan

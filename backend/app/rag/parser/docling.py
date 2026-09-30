"""Docling-based production document parser (Phase 5).

Converts office/PDF/scientific sources into the canonical intermediate using
`Docling <https://ds4sd.github.io/docling/>`_. ``DoclingParser`` is *the*
production path for real manufacturer manuals (PDF/DOCX/…) — there is no
silent plain-text fallback: a ``.pdf`` always goes through Docling and fails
loudly with :class:`~app.rag.errors.RAGParseError` if Docling is missing or the
conversion fails.

Docling is imported lazily on the *first* parse call so ``app.rag`` stays
importable on machines without it (matching the Phase 5 lazy-load convention).
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

from app.rag.config import get_rag_settings
from app.rag.errors import RAGParseError
from app.rag.parser.base import ParseResult, sections_from_text, sha256_hex

# Extensions Docling handles natively. Anything not here and not plain-text is
# rejected by the registry — no silent fallback paths.
DOCLING_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".rtf",
        ".pptx",
        ".ppt",
        ".html",
        ".mhtml",
        ".xlsx",
        ".xls",
        ".odt",
        ".ods",
        ".odp",
        ".epub",
    }
)

PLAIN_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".text"})

# Sticky labels that indicate a heading in Docling's item stream.
_HEADING_LABELS = frozenset(
    {
        "section_header",
        "heading",
        "title",
        "page_header",
        "chapter_title",
        "section_header_group",
    }
)


def _is_heading_label(label: Any) -> bool:
    """True for Docling labels that should feed the section hierarchy."""
    value = getattr(label, "value", None) or str(label)
    value = str(value).strip()
    low = value.casefold()
    return low in _HEADING_LABELS or low.endswith("heading")


class DoclingParser:
    """Production parser backed by Docling (PDF-first)."""

    name = "docling"
    version = "2.130.x"

    def __init__(
        self, *_args: object, page_range: tuple[int, int] | None = None, **_kwargs: object
    ) -> None:
        self._converter: Any | None = None
        self._page_range = page_range

    @property
    def _runtime_version(self) -> str:
        try:
            return importlib.metadata.version("docling")
        except Exception:  # pragma: no cover - env specific
            return self.version

    def _ensure_converter(self) -> Any:
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter
            except Exception as exc:  # pragma: no cover - env specific
                raise RAGParseError(
                    "Docling is not installed; cannot parse this document type"
                ) from exc
            self._converter = DocumentConverter()
            self.version = self._runtime_version
        return self._converter

    def parse(self, path: Path) -> ParseResult:
        converter = self._ensure_converter()
        if not path.exists() or not path.is_file():
            raise RAGParseError(f"source file not found: {path}")
        settings = get_rag_settings()
        if path.stat().st_size > settings.rag_max_document_bytes:
            raise RAGParseError(
                f"{path.name} exceeds the {settings.rag_max_document_bytes}-byte ingest limit"
            )

        kwargs: dict[str, Any] = {
            "raises_on_error": True,
            "max_num_pages": settings.rag_max_document_pages,
            "max_file_size": settings.rag_max_document_bytes,
        }
        if self._page_range is not None:
            kwargs["page_range"] = self._page_range
        try:
            result = converter.convert(path, **kwargs)
        except Exception as exc:  # noqa: BLE001 - docling surfaces many shapes
            raise RAGParseError(f"Docling conversion failed for {path.name}: {exc}") from exc

        document = getattr(result, "document", None)
        if document is None:
            status = getattr(result, "status", None)
            raise RAGParseError(
                f"Docling produced no document for {path.name}"
                + (f" (status={status})" if status is not None else "")
            )

        try:
            text = document.export_to_markdown()
        except Exception as exc:  # noqa: BLE001 - API drift across docling versions
            raise RAGParseError(f"Docling markdown export failed for {path.name}: {exc}") from exc

        # Page-level text buckets + heading -> page map from the item stream.
        page_buckets: dict[int, list[str]] = {}
        heading_pages: dict[str, list[int]] = {}

        items = document.iterate_items() if hasattr(document, "iterate_items") else document.texts
        for item in items:
            text_item = getattr(item, "text", None)
            if not text_item:
                continue
            prov = getattr(item, "prov", None) or []
            pages = sorted({p.page_no for p in prov if getattr(p, "page_no", None)})
            if not pages:
                continue
            for page_no in pages:
                page_buckets.setdefault(page_no, []).append(text_item)
            if _is_heading_label(getattr(item, "label", None)):
                heading_pages.setdefault(text_item.strip().casefold(), []).extend(pages)

        page_count = getattr(document, "num_pages", None)
        page_count = page_count() if callable(page_count) else page_count
        if not page_count:
            page_count = max(page_buckets, default=0) or 0

        pages: list[tuple[int, str]] = sorted(
            (no, "\n\n".join(page_buckets[no])) for no in page_buckets
        )
        sections = sections_from_text(text)
        for sec in sections:
            pages_for_heading = heading_pages.get(sec.heading.strip().casefold())
            if pages_for_heading:
                sec.page_start = min(pages_for_heading)
                sec.page_end = max(pages_for_heading)

        return ParseResult(
            text=text,
            sections=sections,
            pages=pages,
            content_hash=sha256_hex(text),
            page_count=page_count or None,
            metadata={
                "parser": self.name,
                "parser_version": self.version,
                "docling_version": self._runtime_version,
            },
        )


class _UnsupportedParser:
    """Fails deterministically for extensions with no configured parser."""

    name = "unsupported"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def parse(self, path: Path) -> ParseResult:
        raise RAGParseError(f"no parser registered for '{path.suffix or path.name}'")


def get_parser_for(path: Path):
    """Registry: return the parser instance for ``path`` (no lazy loading).

    Raises :class:`~app.rag.errors.RAGParseError` for unsupported extensions —
    production PDFs never silently degrade to a plain-text read.
    """
    if path.suffix.lower() in PLAIN_TEXT_EXTENSIONS:
        from app.rag.parser.plain_text import PlainTextParser

        return PlainTextParser()
    if path.suffix.lower() in DOCLING_EXTENSIONS:
        return DoclingParser()
    return _UnsupportedParser()

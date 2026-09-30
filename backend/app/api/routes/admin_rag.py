"""Admin RAG document management API (Phase 6.x).

Admin-only multipart upload + document lifecycle for the manufacturer corpus,
built on the *existing* Phase 5 ingestion pipeline. Everything in this module
is ``require_admin``-gated:

* ``POST   /api/v1/admin/rag/documents``          — ingest (multipart upload)
* ``GET    /api/v1/admin/rag/documents``          — paginated list + filters
* ``GET    /api/v1/admin/rag/documents/{id}``     — detail + version history
* ``DELETE /api/v1/admin/rag/documents/{id}``     — transactional cascade delete

Semantics mirror the existing ingestion behavior: idempotent content-hash
deduplication returns ``status: unchanged``; re-ingestion of changed content
mints a new immutable version. The route stays thin — all validation and
business logic live in :class:`~app.rag.admin_documents.AdminRagDocumentService`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError

from app.dependencies.auth import require_admin
from app.dependencies.database import get_admin_rag_service
from app.models.user import User
from app.rag.admin_documents import AdminRagDocumentService
from app.rag.schemas import RAGDocumentSummary
from app.schemas.common import PaginatedResponse
from app.schemas.rag import (
    AdminRagDocumentDetailResponse,
    AdminRagDocumentUploadForm,
    AdminRagUploadResponse,
)

router = APIRouter()

#: Form field names accepted by the upload endpoint. Anything else is rejected
#: (422) so a client can never smuggle unknown metadata into the corpus.
UPLOAD_FORM_FIELDS: frozenset[str] = frozenset(
    {
        "file",
        "canonical",
        "make",
        "model",
        "year",
        "manufacturer",
        "title",
        "source_uri",
        "source_type",
        "document_type",
        "year_end",
        "language",
    }
)

_SUPPORTED_FILES_HELP = (
    "Supported document formats follow the parser registry: "
    ".pdf .docx .doc .rtf .pptx .ppt .html .mhtml .xlsx .xls "
    ".txt .md .text"
)


async def _reject_unknown_form_fields(request: Request) -> None:
    """Refuse unknown multipart fields (the API form equivalent of extra=forbid)."""
    form = await request.form()
    unknown = sorted(set(form.keys()) - UPLOAD_FORM_FIELDS)
    if unknown:
        raise RequestValidationError(
            [
                {
                    "type": "extra_forbidden",
                    "loc": ("body", name),
                    "msg": "Extra inputs are not permitted",
                    "input": None,
                }
                for name in unknown
            ]
        )


@router.post(
    "/rag/documents",
    response_model=AdminRagUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a manufacturer document (admin only)",
    description=(
        "Validates the multipart file and metadata, then runs it through the "
        "existing RAG ingestion pipeline (Docling/text parsing, "
        "structure-aware chunking, BGE-M3 embeddings, pgvector). "
        f"{_SUPPORTED_FILES_HELP}."
    ),
    dependencies=[Depends(_reject_unknown_form_fields)],
)
async def upload_document(
    service: Annotated[AdminRagDocumentService, Depends(get_admin_rag_service)],
    admin: Annotated[User, Depends(require_admin)],
    file: Annotated[UploadFile, File(..., description="Document file to ingest")],
    canonical: Annotated[str, Form(..., min_length=1, max_length=512)],
    make: Annotated[str | None, Form(max_length=64)] = None,
    model: Annotated[str | None, Form(max_length=128)] = None,
    year: Annotated[int | None, Form(ge=1900, le=2100)] = None,
    manufacturer: Annotated[str | None, Form(max_length=128)] = None,
    title: Annotated[str | None, Form(max_length=512)] = None,
    source_uri: Annotated[str | None, Form(max_length=1024)] = None,
    source_type: Annotated[str | None, Form(max_length=32)] = None,
    document_type: Annotated[str | None, Form(max_length=32)] = None,
    year_end: Annotated[int | None, Form(ge=1900, le=2100)] = None,
    language: Annotated[str | None, Form(max_length=16)] = None,
) -> AdminRagUploadResponse:
    meta = AdminRagDocumentUploadForm(
        canonical=canonical,
        make=make,
        model=model,
        year=year,
        manufacturer=manufacturer,
        title=title,
        source_uri=source_uri,
        source_type=source_type,
        document_type=document_type,
        year_end=year_end,
        language=language,
    )
    return await service.upload_document(filename=file.filename or "", file=file, meta=meta)


@router.get(
    "/rag/documents",
    response_model=PaginatedResponse[RAGDocumentSummary],
    summary="List corpus documents (admin only)",
    description=(
        "Paginated corpus documents (newest first) with version counts. "
        "Optional exact filters: make, model, canonical; model-year range via "
        "year; documents having a version with the given ingestion status."
    ),
)
async def list_documents(
    service: Annotated[AdminRagDocumentService, Depends(get_admin_rag_service)],
    admin: Annotated[User, Depends(require_admin)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    make: Annotated[str | None, Query(max_length=64)] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    canonical: Annotated[str | None, Query(max_length=512)] = None,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status", max_length=16, description="Version ingestion status (e.g. completed)"
        ),
    ] = None,
) -> PaginatedResponse[RAGDocumentSummary]:
    items, total = await service.list_documents(
        page=page,
        page_size=page_size,
        make=make,
        model=model,
        year=year,
        canonical=canonical,
        status=status_filter,
    )
    return PaginatedResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/rag/documents/{document_id}",
    response_model=AdminRagDocumentDetailResponse,
    summary="Get document detail (admin only)",
    description=(
        "Document identity metadata plus its immutable version history "
        "(content hash, parser, chunk counts, ingestion status per version)."
    ),
)
async def get_document(
    document_id: UUID,
    service: Annotated[AdminRagDocumentService, Depends(get_admin_rag_service)],
    admin: Annotated[User, Depends(require_admin)],
) -> AdminRagDocumentDetailResponse:
    return await service.get_document(document_id)


@router.delete(
    "/rag/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document (admin only)",
    description=(
        "Transactionally removes the document, all of its immutable versions "
        "and every chunk/vector row. RAG search stops returning its content "
        "immediately."
    ),
)
async def delete_document(
    document_id: UUID,
    service: Annotated[AdminRagDocumentService, Depends(get_admin_rag_service)],
    admin: Annotated[User, Depends(require_admin)],
) -> Response:
    await service.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

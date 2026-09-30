import { api } from "@/lib/api-client";
import type {
  AdminRagUploadForm,
  AdminRagUploadResponse,
  PaginatedResponse,
  RagDocumentDetail,
  RagDocumentSummary,
  RagHealthResponse,
  RAGSearchResult,
} from "@/types/api";

/**
 * Phase 5 read-only corpus API.
 *
 * `search` is available to any authenticated user; `health` is admin-only on
 * the backend (403 for everyone else), which is why the admin page surfaces the
 * permission error rather than hiding it.
 */
export const ragApi = {
  search: (
    params: {
      q: string;
      make?: string;
      model?: string;
      year?: number;
      topK?: number;
    },
    signal?: AbortSignal,
  ) =>
    api.get<RAGSearchResult>("/rag/search", {
      query: {
        q: params.q,
        make: params.make,
        model: params.model,
        year: params.year,
        top_k: params.topK,
      },
      ...(signal ? { signal } : {}),
    }),

  health: (signal?: AbortSignal) =>
    api.get<RagHealthResponse>("/rag/health", {
      ...(signal ? { signal } : {}),
    }),
};

/** Phase 6.x admin document management (admin-only server-side). */
export const adminRagApi = {
  list: (
    params: {
      page?: number;
      pageSize?: number;
      make?: string;
      model?: string;
      year?: number;
      canonical?: string;
      status?: string;
    } = {},
    signal?: AbortSignal,
  ) =>
    api.get<PaginatedResponse<RagDocumentSummary>>("/admin/rag/documents", {
      query: {
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
        make: params.make,
        model: params.model,
        year: params.year,
        canonical: params.canonical,
        status: params.status,
      },
      ...(signal ? { signal } : {}),
    }),

  get: (documentId: string, signal?: AbortSignal) =>
    api.get<RagDocumentDetail>(`/admin/rag/documents/${documentId}`, {
      ...(signal ? { signal } : {}),
    }),

  /** Multipart upload; FormData keeps the browser in charge of the boundary. */
  upload: (file: File, meta: AdminRagUploadForm) => {
    const form = new FormData();
    form.append("file", file);
    form.append("canonical", meta.canonical);
    if (meta.make) form.append("make", meta.make);
    if (meta.model) form.append("model", meta.model);
    if (meta.year) form.append("year", String(meta.year));
    if (meta.manufacturer) form.append("manufacturer", meta.manufacturer);
    if (meta.title) form.append("title", meta.title);
    if (meta.source_uri) form.append("source_uri", meta.source_uri);
    if (meta.source_type) form.append("source_type", meta.source_type);
    if (meta.document_type) form.append("document_type", meta.document_type);
    if (meta.year_end) form.append("year_end", String(meta.year_end));
    if (meta.language) form.append("language", meta.language);
    return api.postForm<AdminRagUploadResponse>("/admin/rag/documents", form);
  },

  remove: (documentId: string) =>
    api.delete<void>(`/admin/rag/documents/${documentId}`),
};
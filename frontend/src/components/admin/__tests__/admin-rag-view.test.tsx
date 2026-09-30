import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminRagView } from "@/components/admin/admin-rag-view";
import { adminRagApi, ragApi } from "@/services/rag";
import { useSessionStore } from "@/lib/session-store";
import { renderWithProviders, TEST_USER } from "@/test/utils";
import type {
  AdminRagUploadResponse,
  PaginatedResponse,
  RagDocumentDetail,
  RagDocumentSummary,
  RagHealthResponse,
  RagVersionSummary,
  UserResponse,
} from "@/types/api";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/admin/rag",
}));

const HEALTH: RagHealthResponse = {
  rag_enabled: true,
  pgvector_available: true,
  embedding_adapter: { name: "openai", dimension: 1536 },
  reranker_adapter: { name: "none" },
  embedding_model: "text-embedding-3-small",
  embedding_dimension: 1536,
  corpus_documents: 2,
  corpus_versions: 3,
  corpus_completed_chunks: 118,
};

const DOCUMENTS: PaginatedResponse<RagDocumentSummary> = {
  items: [
    {
      id: "doc-1",
      title: "2019 Civic Service Manual",
      canonical_source: "civic_2019_service_manual",
      source_uri: null,
      source_type: "upload",
      manufacturer: "Honda",
      make: "Honda",
      model: "Civic",
      model_year_start: 2019,
      model_year_end: 2021,
      document_type: "service_manual",
      language: "en",
      version_count: 2,
      created_at: "2026-01-05T00:00:00Z",
      updated_at: "2026-02-01T00:00:00Z",
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
};

const VERSION: RagVersionSummary = {
  id: "ver-1",
  document_id: "doc-1",
  version: 1,
  content_hash: "abc123",
  source_filename: "civic.pdf",
  parser_name: "pymupdf",
  parser_version: "1.24",
  language: "en",
  page_count: 412,
  embedding_model: "text-embedding-3-small",
  embedding_dimension: 1536,
  chunking_version: "v2",
  ingestion_status: "completed",
  error_message: null,
  created_at: "2026-01-05T00:00:00Z",
  chunk_count: 118,
};

const UPLOAD: AdminRagUploadResponse = {
  id: "doc-1",
  status: "ingested",
  filename: "manual.txt",
  canonical: "civic_2019_service_manual",
  make: "Honda",
  model: "Civic",
  year: 2019,
  version: 3,
  chunks_created: 42,
  content_hash: "abc123",
  parser_name: "plaintext",
  embedding_model: "text-embedding-3-small",
  embedding_dimension: 1536,
};

const ADMIN: UserResponse = { ...TEST_USER, role: "admin" };

function asAdmin() {
  useSessionStore.getState().setSession({
    access_token: "token-admin",
    expires_at: new Date(Date.now() + 300_000).toISOString(),
    user: ADMIN,
  });
}

describe("AdminRagView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(ragApi, "health").mockResolvedValue(HEALTH);
    vi.spyOn(adminRagApi, "list").mockResolvedValue(DOCUMENTS);
    vi.spyOn(adminRagApi, "get").mockResolvedValue({
      ...DOCUMENTS.items[0],
      versions: [VERSION],
      latest_version: VERSION,
    } satisfies RagDocumentDetail);
    vi.spyOn(adminRagApi, "remove").mockResolvedValue(undefined);
    vi.spyOn(adminRagApi, "upload").mockResolvedValue(UPLOAD);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useSessionStore.getState().setAnonymous();
  });

  it("blocks non-admins before touching any admin endpoint", async () => {
    useSessionStore.getState().setSession({
      access_token: "token-user",
      expires_at: new Date(Date.now() + 300_000).toISOString(),
      user: TEST_USER,
    });

    renderWithProviders(<AdminRagView />);

    expect(screen.getByText(/administrator access required/i)).toBeTruthy();
    expect(screen.queryByText(/ingest a document/i)).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 50));
    // The server is still the authority, but the client must not even try.
    expect(ragApi.health).not.toHaveBeenCalled();
    expect(adminRagApi.list).not.toHaveBeenCalled();
  });

  it("shows live corpus health to an administrator", async () => {
    asAdmin();
    renderWithProviders(<AdminRagView />);

    expect(await screen.findByText("118")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText(/text-embedding-3-small/)).toBeTruthy();
    expect(await screen.findByText(/2019 Civic Service Manual/)).toBeTruthy();
  });

  it("warns when retrieval is degraded but still allows ingestion", async () => {
    vi.spyOn(ragApi, "health").mockResolvedValue({
      ...HEALTH,
      rag_enabled: false,
      pgvector_available: false,
    });
    asAdmin();
    renderWithProviders(<AdminRagView />);

    expect(await screen.findByText(/retrieval is degraded/i)).toBeTruthy();
    expect(screen.getByText(/ingest a document/i)).toBeTruthy();
  });

  it("uploads through the real multipart endpoint and reports the outcome", async () => {
    const user = userEvent.setup();
    asAdmin();
    const upload = vi.mocked(adminRagApi.upload);
    renderWithProviders(<AdminRagView />);

    const fileInput = await screen.findByLabelText(/document to ingest/i);
    await user.upload(
      fileInput,
      new File(["brake spec text"], "manual.txt", { type: "text/plain" }),
    );
    await user.click(screen.getByRole("button", { name: /ingest document/i }));

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    const [file, meta] = upload.mock.calls[0];
    expect(file.name).toBe("manual.txt");
    expect(meta.canonical).toBe("manual");

    expect(await screen.findByText(/document ingested/i)).toBeTruthy();
    expect(screen.getByText(/created version 3 with 42 chunks/i)).toBeTruthy();
  });

  it("confirms before deleting and calls the endpoint once", async () => {
    const user = userEvent.setup();
    asAdmin();
    renderWithProviders(<AdminRagView />);

    await user.click(
      await screen.findByRole("button", { name: /delete 2019 Civic Service Manual/i }),
    );

    expect(
      screen.getByText(/all 2 version\(s\).*will be removed in a single transaction/i),
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /^delete document$/i }));

    await waitFor(() => expect(adminRagApi.remove).toHaveBeenCalledWith("doc-1"));
  });

  it("cancels the delete without calling the API", async () => {
    const user = userEvent.setup();
    asAdmin();
    renderWithProviders(<AdminRagView />);

    await user.click(
      await screen.findByRole("button", { name: /delete 2019 Civic Service Manual/i }),
    );
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    await waitFor(() => expect(screen.queryByText(/delete this document/i)).toBeNull());
    expect(adminRagApi.remove).not.toHaveBeenCalled();
  });

  it("reports a 403 from the health endpoint rather than pretending it is fine", async () => {
    vi.spyOn(ragApi, "health").mockRejectedValue(
      Object.assign(new Error("Not enough permissions"), { status: 403 }),
    );
    asAdmin();
    renderWithProviders(<AdminRagView />);

    await waitFor(() =>
      expect(screen.getAllByRole("alert").length).toBeGreaterThan(0),
    );
  });
});

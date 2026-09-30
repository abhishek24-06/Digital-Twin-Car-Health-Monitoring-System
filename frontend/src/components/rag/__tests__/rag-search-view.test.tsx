import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RagSearchView } from "@/components/rag/rag-search-view";
import { ragApi } from "@/services/rag";
import { ApiError } from "@/lib/api-error";
import { renderWithProviders, TEST_VEHICLE } from "@/test/utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/rag",
}));

vi.mock("@/hooks/use-vehicle-data", async () => {
  const actual =
    await vi.importActual<typeof import("@/hooks/use-vehicle-data")>(
      "@/hooks/use-vehicle-data",
    );
  return {
    ...actual,
    useVehicles: () => ({ data: [TEST_VEHICLE], isPending: false }),
  };
});

type SearchResult = Awaited<ReturnType<typeof ragApi.search>>;

function evidence(overrides: Partial<SearchResult["results"][number]> = {}) {
  return {
    chunk_id: "chunk-1",
    document_id: "doc-1",
    document_version_id: "docv-1",
    document_version: 1,
    title: "2019 Civic Service Manual",
    manufacturer: "Honda",
    make: "Honda",
    model: "Civic",
    model_year_start: 2019,
    model_year_end: 2019,
    document_type: "service_manual",
    source_filename: "civic_2019_service_manual.pdf",
    section_title: "Cooling System",
    heading_path: ["Cooling System"],
    page_start: 214,
    page_end: 214,
    content: "Inspect the water pump weep hole for coolant residue.",
    scope: "EXACT_VEHICLE" as const,
    dense_score: 0.71,
    lexical_score: 0.4,
    hybrid_score: 0.62,
    rerank_score: 0.82,
    metadata: {},
    ...overrides,
  };
}

describe("RagSearchView", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("presents a reachable-but-empty result as an empty state, not an outage", async () => {
    const user = userEvent.setup();
    // The live API returns exactly this when nothing matched: available:false
    // with the retrieval *mode* in `reason`.
    vi.spyOn(ragApi, "search").mockResolvedValue({
      query: "brake wear",
      vehicle_scope: { make: "Honda", model: null, year: null, engine: null, region: null },
      available: false,
      reason: "hybrid",
      results: [],
      metrics: {},
    } as SearchResult);

    renderWithProviders(<RagSearchView />);

    await user.type(screen.getByLabelText(/question or phrase/i), "brake wear");
    await user.click(screen.getByRole("button", { name: /^search/i }));

    expect(await screen.findByText(/no passages matched/i)).toBeTruthy();
    expect(screen.getByText(/searched successfully but nothing matched/i)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("asks for a query when the backend reports an empty query", async () => {
    const user = userEvent.setup();
    vi.spyOn(ragApi, "search").mockResolvedValue({
      query: "",
      vehicle_scope: null,
      available: false,
      reason: "empty-query",
      results: [],
      metrics: {},
    } as SearchResult);

    renderWithProviders(<RagSearchView />);

    await user.type(screen.getByLabelText(/question or phrase/i), "brake wear");
    await user.click(screen.getByRole("button", { name: /^search/i }));

    expect(await screen.findByText(/enter a question/i)).toBeTruthy();
  });

  it("shows a 503 from the route as a retrieval outage", async () => {
    const user = userEvent.setup();
    // RAG disabled or pgvector missing: the route raises 503, not a 200 body.
    vi.spyOn(ragApi, "search").mockRejectedValue(
      new ApiError(503, "RAG is disabled by configuration"),
    );

    renderWithProviders(<RagSearchView />);

    await user.type(screen.getByLabelText(/question or phrase/i), "brake wear");
    await user.click(screen.getByRole("button", { name: /^search/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /RAG is disabled by configuration/i,
      ),
    );
  });

  it("scopes the query to the active vehicle when asked to", async () => {
    const user = userEvent.setup();
    const search = vi.spyOn(ragApi, "search").mockResolvedValue({
      query: "coolant leak",
      vehicle_scope: { make: "Honda", model: "Civic", year: 2019 },
      available: true,
      reason: "",
      results: [evidence()],
      metrics: {},
    } as SearchResult);

    renderWithProviders(<RagSearchView />);

    await user.type(screen.getByLabelText(/question or phrase/i), "coolant leak");
    await user.click(screen.getByRole("button", { name: /^search/i }));

    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    expect(search.mock.calls[0][0]).toMatchObject({
      q: "coolant leak",
      make: "Honda",
      model: "Civic",
      year: 2019,
    });
  });

  it("renders a passage with its citation and truncates long text", async () => {
    const user = userEvent.setup();
    vi.spyOn(ragApi, "search").mockResolvedValue({
      query: "coolant leak",
      vehicle_scope: null,
      available: true,
      reason: "",
      results: [evidence({ content: "x".repeat(400) })],
      metrics: {},
    } as SearchResult);

    renderWithProviders(<RagSearchView />);

    await user.type(screen.getByLabelText(/question or phrase/i), "coolant leak");
    await user.click(screen.getByRole("button", { name: /^search/i }));

    expect(await screen.findByText(/2019 Civic Service Manual/i)).toBeTruthy();
    // Section, filename and page are all cited with the passage.
    expect(
      screen.getByText(/Cooling System · civic_2019_service_manual\.pdf · p\.214/),
    ).toBeTruthy();
    expect(screen.getByText(/Exact vehicle/i)).toBeTruthy();

    // Collapsed by default, expandable on demand.
    expect(screen.getByRole("button", { name: /show full passage/i })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /show full passage/i }));
    expect(screen.getByRole("button", { name: /show less/i })).toBeTruthy();
  });

  it("reports a retrieval failure as an error, not as zero results", async () => {
    const user = userEvent.setup();
    vi.spyOn(ragApi, "search").mockRejectedValue(
      Object.assign(new Error("The retrieval service is unavailable."), {
        name: "ApiError",
        status: 503,
      }),
    );

    renderWithProviders(<RagSearchView />);

    await user.type(screen.getByLabelText(/question or phrase/i), "brake wear");
    await user.click(screen.getByRole("button", { name: /^search/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/unavailable/i),
    );
    expect(screen.queryByText(/no passages matched/i)).toBeNull();
  });

  it("does not call the API for an empty query", async () => {
    const search = vi.spyOn(ragApi, "search");
    renderWithProviders(<RagSearchView />);
    await userEvent.click(screen.getByRole("button", { name: /^search/i }));
    expect(search).not.toHaveBeenCalled();
  });
});

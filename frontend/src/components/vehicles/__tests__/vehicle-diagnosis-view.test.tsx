import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VehicleDiagnosisView } from "@/components/vehicles/vehicle-diagnosis-view";
import { agentApi } from "@/services/vehicles";
import { ApiError } from "@/lib/api-error";
import { renderWithProviders } from "@/test/utils";
import type { DiagnosisResponse } from "@/types/api";

const paramsMock = vi.fn(() => ({ id: "22222222-2222-4222-8222-222222222222" }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/vehicles/v1/diagnosis",
  useParams: () => paramsMock(),
}));

const DIAGNOSIS = {
  id: "33333333-3333-4333-8333-333333333333",
  vehicle_id: "22222222-2222-4222-8222-222222222222",
  trigger_type: "user_query",
  severity: "warning",
  confidence: 0.78,
  generated_at: "2026-02-01T10:00:00Z",
  diagnosis: {
    summary: "Front brake pads are near the wear limit.",
    possible_causes: [
      {
        cause: "Worn friction material",
        likelihood: "high",
        matching_evidence: ["brake_pad_wear_pct >= 80"],
        recommended_actions: [],
      },
    ],
    recommended_actions: [
      {
        action: "Inspect pads at the next service",
        priority: "medium",
        category: "maintenance",
      },
    ],
    evidence: [],
    severity_analysis: {
      assessed_severity: "warning",
      rule_severity: "warning",
      rationale: "Wear above the attention threshold.",
    },
    confidence_analysis: {
      assessed_confidence: 0.78,
      deterministic_confidence: 0.8,
      score_quality: "high",
      data_quality: "good",
      rationale: "Recent telemetry present.",
      validation_warnings: [],
    },
    context_note: "",
    manufacturer_guidance: "",
    cited_sources: [],
    citations: [],
    manufacturer_evidence: [],
  },
  user_query: "Why is my brake pedal noisy?",
  context_timestamp: "2026-02-01T09:59:00Z",
  execution: {
    provider: "openai",
    model: "gpt-4o-mini",
    rag_used: false,
    rag_evidence_count: 0,
    rag_embedding_model: null,
    rag_reranker_model: null,
    latency_ms: 812,
    fallback_used: false,
  },
  evidence: [],
} as unknown as DiagnosisResponse;

describe("VehicleDiagnosisView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: the real backend 404s when a vehicle has no diagnosis yet.
    vi.spyOn(agentApi, "latest").mockRejectedValue(
      new ApiError(404, "Diagnosis not found"),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("turns a missing diagnosis (404) into an empty state, not an error", async () => {
    renderWithProviders(<VehicleDiagnosisView />);

    await waitFor(() => expect(screen.getByText(/no diagnosis yet/i)).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("surfaces a non-404 failure from the latest-diagnosis fetch", async () => {
    vi.spyOn(agentApi, "latest").mockRejectedValue(
      new ApiError(503, "The service is temporarily unavailable."),
    );

    renderWithProviders(<VehicleDiagnosisView />);

    // The hook retries once, so allow for the backoff before asserting.
    await waitFor(
      () => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0),
      { timeout: 4000 },
    );
  });

  it("shows the backend's sanitized 502 when no AI provider is configured", async () => {
    const user = userEvent.setup();
    vi.spyOn(agentApi, "ask").mockRejectedValue(
      new ApiError(502, "The AI provider is not configured.", {
        code: "provider_unavailable",
      }),
    );

    renderWithProviders(<VehicleDiagnosisView />);

    await user.type(
      screen.getByLabelText(/question about this vehicle/i),
      "Why is my brake pedal noisy?",
    );
    await user.click(screen.getByRole("button", { name: /ask the agent/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /provider is not configured/i,
      ),
    );
    // Health scoring is independent of the LLM, and the UI must say so.
    expect(
      screen.getByText(/rule-based health score are unaffected/i),
    ).toBeTruthy();
    expect(screen.getByText(/no diagnosis yet/i)).toBeTruthy();
  });

  it("renders a grounded diagnosis with its causes and actions", async () => {
    const user = userEvent.setup();
    vi.spyOn(agentApi, "ask").mockResolvedValue(DIAGNOSIS);

    renderWithProviders(<VehicleDiagnosisView />);

    await user.type(screen.getByLabelText(/question about this vehicle/i), "brake noise");
    await user.click(screen.getByRole("button", { name: /ask the agent/i }));

    expect(
      await screen.findByText(/front brake pads are near the wear limit/i),
    ).toBeTruthy();
    expect(screen.getByText(/Worn friction material/)).toBeTruthy();
    expect(screen.getByText(/Inspect pads at the next service/)).toBeTruthy();
    expect(screen.getByText(/confidence 78%/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("requires a real question before the agent will be called", async () => {
    const ask = vi.spyOn(agentApi, "ask");
    renderWithProviders(<VehicleDiagnosisView />);

    const submit = screen.getByRole("button", { name: /ask the agent/i });
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/question about this vehicle/i), "ab");
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/question about this vehicle/i), "c");
    expect(submit).not.toBeDisabled();
    expect(ask).not.toHaveBeenCalled();
  });

  it("shows the persisted latest diagnosis on load", async () => {
    vi.spyOn(agentApi, "latest").mockResolvedValue(DIAGNOSIS);

    renderWithProviders(<VehicleDiagnosisView />);

    expect(
      await screen.findByText(/front brake pads are near the wear limit/i),
    ).toBeTruthy();
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { VehicleHealthView } from "@/components/vehicles/vehicle-health-view";
import {
  createWorkflowStreamHarness,
  renderWithProviders,
  TEST_VEHICLE,
} from "@/test/utils";
import type { WorkflowEventResponse } from "@/types/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: TEST_VEHICLE.id }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/vehicles/1/health",
}));

vi.mock("@/hooks/use-vehicle-data", async () => {
  const actual = await vi.importActual<
    typeof import("@/hooks/use-vehicle-data")
  >("@/hooks/use-vehicle-data");
  return {
    ...actual,
    useHealthContext: () => ({
      data: null,
      isPending: false,
      isError: false,
      error: null,
      refetch: () => {},
    }),
  };
});

vi.mock("@/hooks/use-mutations", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/use-mutations")>(
    "@/hooks/use-mutations",
  );
  return {
    ...actual,
    useAnalyzeHealth: () => ({
      isPending: false,
      isError: false,
      error: null,
      mutate: vi.fn(),
    }),
  };
});

function healthEvent(
  overrides: Partial<WorkflowEventResponse> = {},
): WorkflowEventResponse {
  return {
    event_id: "health-evt",
    timestamp: "2026-01-01T00:00:00Z",
    workflow: "health",
    stage: "health_score_calculated",
    status: "running",
    message: "Scoring",
    vehicle_id: TEST_VEHICLE.id,
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

describe("VehicleHealthView contextual health pipeline", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("shows waiting stages before any analysis has run", () => {
    renderWithProviders(<VehicleHealthView />);

    expect(screen.getByText("Health Pipeline")).toBeTruthy();
    expect(screen.getAllByText("Waiting").length).toBeGreaterThan(0);
  });

  it("updates the score stage from a real health event", async () => {
    const harness = createWorkflowStreamHarness();
    renderWithProviders(<VehicleHealthView />, {
      eventSourceFactory: harness.factory,
    });

    harness.latest().emit(
      healthEvent({ stage: "health_score_calculated", status: "success" }),
    );

    expect(await screen.findByText("Success")).toBeTruthy();
  });

  it("keeps the deterministic score explanation rendering", () => {
    renderWithProviders(<VehicleHealthView />);
    expect(screen.getByText("How this score is produced")).toBeTruthy();
  });
});

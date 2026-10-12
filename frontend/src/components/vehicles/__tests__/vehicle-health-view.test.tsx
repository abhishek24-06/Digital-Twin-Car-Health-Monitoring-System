import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { VehicleHealthView } from "@/components/vehicles/vehicle-health-view";
import { useLiveHealth } from "@/hooks/use-vehicle-data";
import {
  createWorkflowStreamHarness,
  renderWithProviders,
  TEST_VEHICLE,
} from "@/test/utils";
import type { LiveHealthStatusResponse, WorkflowEventResponse } from "@/types/api";

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
    useLiveHealth: vi.fn(),
  };
});

function live(
  overrides: Partial<LiveHealthStatusResponse> = {},
): LiveHealthStatusResponse {
  return {
    vehicle_id: TEST_VEHICLE.id,
    run_id: null,
    simulator_state: "stopped",
    live_state: "no_session",
    latest_source_timestamp: null,
    latest_persisted_at: null,
    sample_count: 0,
    required_sample_count: 30,
    observation_duration_seconds: null,
    required_duration_seconds: 30,
    coverage_ratio: null,
    required_coverage: 0.5,
    latest_sample_age_seconds: null,
    max_sample_age_seconds: 15,
    sample_timestamp_order_valid: true,
    insufficiency_reasons: [],
    assessment: null,
    last_evaluated_at: null,
    message: "No simulator run is active for this vehicle; there is no current session to assess.",
    ...overrides,
  };
}

const assessment: NonNullable<LiveHealthStatusResponse["assessment"]> = {
  vehicle_id: TEST_VEHICLE.id,
  context_schema_version: "1.2",
  rule_engine_version: "1.0",
  generated_at: "2026-01-01T10:00:06Z",
  analysis_duration_ms: 12,
  analysis_window: {
    start: "2026-01-01T09:59:30Z",
    end: "2026-01-01T10:00:00Z",
    window_minutes: 0.5,
  },
  data_quality: {
    sample_count: 45,
    expected_sample_count: 50,
    coverage_ratio: 0.9,
    first_timestamp: "2026-01-01T09:59:30Z",
    last_timestamp: "2026-01-01T10:00:00Z",
    duration_seconds: 30,
    missing_sample_estimate: 5,
    max_gap_seconds: null,
    timestamp_order_valid: true,
  },
  statistics: {},
  trends: [],
  baselines: [],
  findings: [],
  health_score: 88.0,
  health_status: "healthy",
  confidence: 0.86,
  score_details: {
    score: 88,
    status: "healthy",
    starting_score: 100,
    total_penalty: 12,
    components: [],
    notes: [],
  },
  data_sufficiency: "sufficient_data",
  provisional: false,
  provisional_rating: null,
  simulation_run_id: "a1a1a1a1-0000-4000-8000-000000000001",
  live_sufficiency: {
    policy_met: true,
    sample_count: 45,
    required_sample_count: 30,
    observation_duration_seconds: 45,
    required_duration_seconds: 30,
    coverage_ratio: 0.8,
    required_coverage: 0.5,
    latest_sample_age_seconds: 2,
    max_sample_age_seconds: 15,
    reasons: [],
  },
  analysis_scope: "current_session",
};

function mockLive(status: LiveHealthStatusResponse) {
  vi.mocked(useLiveHealth).mockReturnValue({
    data: status,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useLiveHealth>);
}

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

describe("VehicleHealthView live current-session", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("shows waiting stages before any analysis has run", () => {
    mockLive(live());
    renderWithProviders(<VehicleHealthView />);

    expect(screen.getByText("Health Pipeline")).toBeTruthy();
    expect(screen.getAllByText("Waiting").length).toBeGreaterThan(0);
  });

  it("updates the score stage from a real health event", async () => {
    mockLive(live());
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
    mockLive(live());
    renderWithProviders(<VehicleHealthView />);
    expect(screen.getByText("How this score is produced")).toBeTruthy();
  });

  it("shows no current-session assessment and no window selector without an active run", () => {
    mockLive(live());
    renderWithProviders(<VehicleHealthView />);

    expect(screen.getByText("No active session")).toBeTruthy();
    // A historical/last-known score must never be dressed up as current.
    expect(screen.queryByText("Report scope")).toBeNull();
    // Historical window selection lives under Analytics, not the live view.
    expect(screen.queryByText("Historical report window")).toBeNull();
    expect(screen.queryByText("Analysis window")).toBeNull();
  });

  it("renders the definitive current-session assessment with its scope", () => {
    mockLive(
      live({
        run_id: assessment.simulation_run_id,
        simulator_state: "running",
        live_state: "fresh",
        sample_count: 45,
        observation_duration_seconds: 45,
        coverage_ratio: 0.8,
        latest_sample_age_seconds: 2,
        assessment,
      }),
    );
    renderWithProviders(<VehicleHealthView />);

    expect(screen.getByText("definitive live assessment")).toBeTruthy();
    expect(screen.getByText(/Report scope/)).toBeTruthy();
    expect(screen.getByText("88.0")).toBeTruthy();
    expect(screen.getByText("Statistics")).toBeTruthy();
    expect(screen.queryByText("No active session")).toBeNull();
  });

  it("marks a stale live feed without reusing a score", () => {
    mockLive(
      live({
        run_id: "a1a1a1a1-0000-4000-8000-000000000002",
        simulator_state: "running",
        live_state: "stale",
        sample_count: 40,
        observation_duration_seconds: 40,
        coverage_ratio: 1,
        latest_sample_age_seconds: 60,
        insufficiency_reasons: ["newest sample is older than the freshness limit"],
        message: "Current-session feed is stale.",
      }),
    );
    renderWithProviders(<VehicleHealthView />);

    expect(screen.getAllByText("Current-session feed is stale").length).toBeGreaterThan(0);
    expect(screen.queryByText("Report scope")).toBeNull();
  });
});

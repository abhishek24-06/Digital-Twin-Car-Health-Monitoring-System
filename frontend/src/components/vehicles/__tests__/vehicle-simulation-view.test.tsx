import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { VehicleSimulationView } from "@/components/vehicles/vehicle-simulation-view";
import { renderWithProviders, TEST_VEHICLE } from "@/test/utils";
import { useLiveHealth } from "@/hooks/use-vehicle-data";
import type { LiveHealthStatusResponse } from "@/types/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: TEST_VEHICLE.id }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/vehicles/1/simulation",
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
    run_id: "46c9b21e-0c84-4d2c-8b2b-7b1c0f0a3a71",
    simulator_state: "running",
    live_state: "collecting",
    latest_source_timestamp: "2026-01-01T10:00:05Z",
    latest_persisted_at: "2026-01-01T10:00:05Z",
    sample_count: 12,
    required_sample_count: 30,
    observation_duration_seconds: 18,
    required_duration_seconds: 30,
    coverage_ratio: 0.12,
    required_coverage: 0.5,
    latest_sample_age_seconds: 2,
    max_sample_age_seconds: 15,
    sample_timestamp_order_valid: true,
    insufficiency_reasons: [
      "needs at least 30 current-run samples",
      "needs at least 50% coverage",
    ],
    assessment: null,
    last_evaluated_at: "2026-01-01T10:00:06Z",
    message: "The current run is still collecting evidence.",
    ...overrides,
  };
}

const assessment: NonNullable<LiveHealthStatusResponse["assessment"]> = {
  vehicle_id: TEST_VEHICLE.id,
  context_schema_version: "1.0",
  rule_engine_version: "1.0",
  generated_at: "2026-01-01T10:00:06Z",
  analysis_duration_ms: 12,
  analysis_window: {
    start: "2026-01-01T09:30:00Z",
    end: "2026-01-01T10:00:00Z",
    window_minutes: 30,
  },
  data_quality: {
    sample_count: 45,
    expected_sample_count: 60,
    coverage_ratio: 0.8,
    first_timestamp: "2026-01-01T09:30:00Z",
    last_timestamp: "2026-01-01T10:00:00Z",
    duration_seconds: 1800,
    missing_sample_estimate: 15,
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
};

describe("VehicleSimulationView live session status", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("surfaces the run id and honest collecting state with reasons", () => {
    vi.mocked(useLiveHealth).mockReturnValue({
      data: live(),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useLiveHealth>);

    renderWithProviders(<VehicleSimulationView />);

    expect(screen.getByText("Live simulation status")).toBeTruthy();
    expect(screen.getByText("collecting data")).toBeTruthy();
    expect(
      screen.getByText("46c9b21e-0c84-4d2c-8b2b-7b1c0f0a3a71"),
    ).toBeTruthy();
    expect(screen.getByText("Why the live view is not definitive yet")).toBeTruthy();
    expect(
      screen.getByText("The current run is still collecting evidence."),
    ).toBeTruthy();
  });

  it("shows a definitive assessment only for a fresh sufficient run", () => {
    vi.mocked(useLiveHealth).mockReturnValue({
      data: live({
        live_state: "fresh",
        run_id: "a1a1a1a1-0000-4000-8000-000000000001",
        sample_count: 45,
        observation_duration_seconds: 45,
        coverage_ratio: 0.8,
        insufficiency_reasons: [],
        message: "The live assessment reflects the current run.",
        assessment,
      }),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useLiveHealth>);

    renderWithProviders(<VehicleSimulationView />);

    expect(screen.getByText("fresh")).toBeTruthy();
    expect(screen.getByText("definitive live assessment")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.queryByText("Why the live view is not definitive yet")).toBeNull();
  });

  it("never invents a session when no run is active", () => {
    vi.mocked(useLiveHealth).mockReturnValue({
      data: live({
        run_id: null,
        simulator_state: "stopped",
        live_state: "no_session",
        sample_count: 0,
        observation_duration_seconds: null,
        coverage_ratio: null,
        latest_sample_age_seconds: null,
        insufficiency_reasons: [],
        message: null,
      }),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useLiveHealth>);

    renderWithProviders(<VehicleSimulationView />);

    expect(screen.getByText("no session")).toBeTruthy();
    expect(
      screen.getByText(/No simulator run is active for this vehicle/),
    ).toBeTruthy();
    expect(screen.queryByText("definitive live assessment")).toBeNull();
  });
});
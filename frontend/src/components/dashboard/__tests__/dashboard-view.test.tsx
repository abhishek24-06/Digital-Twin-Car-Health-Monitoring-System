import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import { ApiError } from "@/lib/api-error";
import { renderWithProviders, TEST_VEHICLE } from "@/test/utils";
import type {
  FleetAssessmentSummary,
  FleetOverviewResponse,
  FleetTotals,
  FleetVehicleSummary,
  HealthDbResponse,
  HealthResponse,
  WorkflowStatusResponse,
} from "@/types/api";

const { overviewMock, livenessMock, databaseMock, workflowStatusMock } = vi.hoisted(
  () => ({
    overviewMock: vi.fn(),
    livenessMock: vi.fn(),
    databaseMock: vi.fn(),
    workflowStatusMock: vi.fn(),
  }),
);

vi.mock("@/services/fleet", () => ({
  fleetApi: { overview: overviewMock },
  systemApi: { liveness: livenessMock, database: databaseMock },
}));

vi.mock("@/services/workflow", async () => {
  const actual = await vi.importActual<typeof import("@/services/workflow")>(
    "@/services/workflow",
  );
  return {
    ...actual,
    workflowApi: { ...actual.workflowApi, getWorkflowStatus: workflowStatusMock },
  };
});

/** A fixed instant used to assert timestamp labels deterministically. */
const NOW = new Date("2026-03-01T12:00:00Z");
const UUID_RE =
  /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

function iso(offsetMs: number): string {
  return new Date(NOW.getTime() + offsetMs).toISOString();
}

function totals(overrides: Partial<FleetTotals> = {}): FleetTotals {
  return {
    vehicles: 0,
    vehicles_with_recent_telemetry: 0,
    vehicles_requiring_attention: 0,
    vehicles_with_open_alerts: 0,
    active_simulations: 0,
    open_alerts: 0,
    critical_open_alerts: 0,
    ...overrides,
  };
}

function assessment(
  overrides: Partial<FleetAssessmentSummary> = {},
): FleetAssessmentSummary {
  return {
    health_status: "healthy",
    provisional_rating: null,
    health_score: 96,
    confidence: 0.92,
    generated_at: iso(-60_000),
    provisional: false,
    data_sufficiency: "sufficient_data",
    analysis_scope: "current_session",
    sample_count: 120,
    ...overrides,
  };
}

function vehicle(
  overrides: Partial<FleetVehicleSummary> = {},
): FleetVehicleSummary {
  return {
    vehicle_id: TEST_VEHICLE.id,
    vin: TEST_VEHICLE.vin,
    make: TEST_VEHICLE.make,
    model: TEST_VEHICLE.model,
    year: TEST_VEHICLE.year,
    engine_type: TEST_VEHICLE.engine_type,
    status: "active",
    simulation_state: "stopped",
    simulation_scenario: null,
    simulation_started_at: null,
    simulation_error: null,
    last_telemetry_at: null,
    telemetry_freshness: "no_data",
    assessment: null,
    assessment_freshness: "none",
    open_alerts: 0,
    critical_open_alerts: 0,
    warning_open_alerts: 0,
    requires_attention: false,
    ...overrides,
  };
}

function overview(
  vehicles: FleetVehicleSummary[],
  overrides: Partial<FleetOverviewResponse> = {},
): FleetOverviewResponse {
  return {
    generated_at: iso(0),
    telemetry_stale_after_seconds: 30,
    assessment_stale_after_seconds: 100,
    totals: totals({ vehicles: vehicles.length }),
    vehicles,
    ...overrides,
  };
}

function secondVehicle(
  overrides: Partial<FleetVehicleSummary> = {},
): FleetVehicleSummary {
  return vehicle({
    vehicle_id: "33333333-3333-4333-8333-333333333333",
    vin: "1HGCM82633A009999",
    make: "Toyota",
    model: "Corolla",
    year: 2021,
    engine_type: "2.0L",
    ...overrides,
  });
}

beforeEach(() => {
  livenessMock.mockResolvedValue({
    status: "ok",
    service: "digital-twin-api",
  } satisfies HealthResponse);
  databaseMock.mockResolvedValue({
    status: "ok",
    service: "digital-twin-api",
    database: "ok",
  } satisfies HealthDbResponse);
  workflowStatusMock.mockResolvedValue({
    telemetry_pipeline_active: true,
    rag_pipeline_active: false,
    agent_pipeline_active: false,
    subscriber_running: true,
    active_simulations: 0,
    events_in_buffer: 0,
    oldest_event_ts: null,
    newest_event_ts: null,
  } satisfies WorkflowStatusResponse);
  overviewMock.mockResolvedValue(overview([]));
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("DashboardView — fleet overview", () => {
  it("is fleet-level and never centres on a single vehicle", async () => {
    overviewMock.mockResolvedValue(overview([vehicle(), secondVehicle()]));

    renderWithProviders(<DashboardView />);

    expect(
      await screen.findByRole("heading", {
        name: /vehicle intelligence overview/i,
      }),
    ).toBeTruthy();
    expect(await screen.findByText("Honda Civic")).toBeTruthy();
    expect(screen.getByText("Toyota Corolla")).toBeTruthy();
    // No raw UUIDs leak into the DOM.
    expect(screen.queryByText(UUID_RE)).toBeNull();
  });

  it("shows a loading skeleton before the first snapshot arrives", () => {
    overviewMock.mockReturnValue(new Promise<FleetOverviewResponse>(() => {}));

    renderWithProviders(<DashboardView />);

    expect(screen.getByText(/loading the fleet snapshot/i)).toBeTruthy();
    expect(screen.queryByText("Honda Civic")).toBeNull();
  });

  it("renders each KPI from the real fleet totals", async () => {
    overviewMock.mockResolvedValue(
      overview([vehicle()], {
        totals: totals({
          vehicles: 4,
          vehicles_with_recent_telemetry: 2,
          vehicles_requiring_attention: 1,
          vehicles_with_open_alerts: 1,
          active_simulations: 2,
          open_alerts: 3,
          critical_open_alerts: 1,
        }),
      }),
    );

    renderWithProviders(<DashboardView />);

    await screen.findByTestId("kpi-vehicles");
    expect(within(screen.getByTestId("kpi-vehicles")).getByText("4")).toBeTruthy();
    expect(
      within(screen.getByTestId("kpi-recent")).getByText("of 4"),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("kpi-attention")).getByText("1"),
    ).toBeTruthy();
    expect(within(screen.getByTestId("kpi-alerts")).getByText("3")).toBeTruthy();
    expect(
      within(screen.getByTestId("kpi-alerts")).getByText(/1 of them critical/i),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("kpi-sims")).getByText("2"),
    ).toBeTruthy();
  });

  it("labels telemetry freshness as Live or Stale per vehicle", async () => {
    overviewMock.mockResolvedValue(
      overview([
        vehicle({
          telemetry_freshness: "recent",
          last_telemetry_at: iso(-5_000),
        }),
        secondVehicle({
          telemetry_freshness: "stale",
          last_telemetry_at: iso(-3_600_000),
        }),
      ]),
    );

    renderWithProviders(<DashboardView />);

    await screen.findByText("Honda Civic");
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.getByText("Stale")).toBeTruthy();
  });

  it("labels a vehicle that has never sent telemetry as No data", async () => {
    overviewMock.mockResolvedValue(overview([vehicle()]));

    renderWithProviders(<DashboardView />);

    await screen.findByText("Honda Civic");
    expect(screen.getAllByText("No data").length).toBeGreaterThan(0);
  });

  it("renders telemetry age against a fixed clock", async () => {
    vi.spyOn(Date, "now").mockReturnValue(NOW.getTime());
    overviewMock.mockResolvedValue(
      overview([
        vehicle({
          telemetry_freshness: "recent",
          last_telemetry_at: iso(-5 * 60_000),
        }),
      ]),
    );

    renderWithProviders(<DashboardView />);

    expect(await screen.findByText("5 minutes ago")).toBeTruthy();
  });

  it("labels a stored assessment with its own timestamp, not the render time", async () => {
    vi.spyOn(Date, "now").mockReturnValue(NOW.getTime());
    overviewMock.mockResolvedValue(
      overview([
        vehicle({
          assessment: assessment({ generated_at: iso(-2 * 3_600_000) }),
          assessment_freshness: "stale",
        }),
      ]),
    );

    renderWithProviders(<DashboardView />);

    expect(await screen.findByText(/Assessed 2 hours ago/)).toBeTruthy();
    // The absolute timestamp is shown alongside the relative one.
    expect(screen.getByText(/Score 96\/100/)).toBeTruthy();
  });

  it("marks an aged assessment as Aged and keeps it out of the attention list", async () => {
    overviewMock.mockResolvedValue(
      overview([
        vehicle({
          assessment: assessment({
            health_status: "critical",
            health_score: 20,
            generated_at: iso(-3 * 3_600_000),
          }),
          assessment_freshness: "stale",
          requires_attention: false,
        }),
      ]),
    );

    renderWithProviders(<DashboardView />);

    await screen.findByText("Honda Civic");
    expect(screen.getAllByText("Aged").length).toBeGreaterThan(0);
    expect(await screen.findByText("Nothing needs attention")).toBeTruthy();
  });

  it("presents a provisional assessment as provisional, not definitive", async () => {
    overviewMock.mockResolvedValue(
      overview([
        vehicle({
          assessment: assessment({
            health_status: "limited_data",
            provisional: true,
            provisional_rating: "healthy",
            health_score: null,
            data_sufficiency: "limited_data",
          }),
          assessment_freshness: "fresh",
        }),
        secondVehicle({
          assessment: assessment({
            health_status: "limited_data",
            provisional: true,
            provisional_rating: "critical",
            health_score: null,
            data_sufficiency: "limited_data",
          }),
          assessment_freshness: "fresh",
          requires_attention: true,
        }),
      ]),
    );

    renderWithProviders(<DashboardView />);

    await screen.findByText("Honda Civic");
    // The caveat is always shown next to a provisional rating.
    expect(screen.getAllByText("Provisional").length).toBeGreaterThan(0);
    // A provisional critical is a real problem and is listed for attention.
    expect(
      (await screen.findAllByText(/Current assessment is critical/)).length,
    ).toBeGreaterThan(0);
  });

  it("lists only flagged vehicles in the attention panel, with a reason", async () => {
    overviewMock.mockResolvedValue(
      overview([
        vehicle({
          requires_attention: true,
          open_alerts: 2,
          critical_open_alerts: 1,
          warning_open_alerts: 1,
        }),
        secondVehicle(),
      ]),
    );

    renderWithProviders(<DashboardView />);

    const heading = await screen.findByRole("heading", {
      name: /needs attention/i,
    });
    const panel = heading.closest("section");
    expect(panel).toBeTruthy();
    expect(within(panel as HTMLElement).getByText(/2 active alerts/)).toBeTruthy();
    expect(
      within(panel as HTMLElement).queryByText("Toyota Corolla"),
    ).toBeNull();
  });

  it("shows an empty state with a register call to action for an empty fleet", async () => {
    renderWithProviders(<DashboardView />);

    expect(await screen.findByText("No vehicles yet")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /register a vehicle/i }),
    ).toBeTruthy();
  });

  it("uses a single detailed layout when there is exactly one vehicle", async () => {
    overviewMock.mockResolvedValue(
      overview([
        vehicle({
          assessment: assessment({ health_status: "attention", health_score: 58 }),
          assessment_freshness: "fresh",
          requires_attention: true,
        }),
      ]),
    );

    renderWithProviders(<DashboardView />);

    await screen.findAllByText("Honda Civic");
    // The detailed card exposes the full assessment block.
    expect(screen.getByText(/Score 58\/100/)).toBeTruthy();
    expect(screen.getByText(/confidence 92%/)).toBeTruthy();
  });

  it("keeps a large fleet scannable as a grid of cards", async () => {
    const fleet = Array.from({ length: 6 }, (_, index) =>
      vehicle({
        vehicle_id: `44444444-4444-4444-8444-${String(index).padStart(12, "0")}`,
        vin: `VIN0000000000000${index}`,
        model: `Model ${index}`,
      }),
    );
    overviewMock.mockResolvedValue(overview(fleet));

    renderWithProviders(<DashboardView />);

    await screen.findByText(/Model 0/);
    for (const item of fleet) {
      expect(screen.getByTestId(`fleet-vehicle-${item.vehicle_id}`)).toBeTruthy();
    }
  });

  it("shows an error state with retry when the fleet snapshot fails", async () => {
    const user = userEvent.setup();
    overviewMock.mockRejectedValue(new ApiError(500, "fleet exploded"));

    renderWithProviders(<DashboardView />);

    const retry = await screen.findByRole("button", { name: /retry fleet/i });
    const callsBefore = overviewMock.mock.calls.length;
    await user.click(retry);

    await waitFor(() =>
      expect(overviewMock.mock.calls.length).toBeGreaterThan(callsBefore),
    );
  });

  it("degrades only the pipeline panel when workflow status is unavailable", async () => {
    workflowStatusMock.mockRejectedValue(new ApiError(500, "workflow down"));
    overviewMock.mockResolvedValue(overview([vehicle()]));

    renderWithProviders(<DashboardView />);

    const ingestion = await screen.findByTestId("platform-ingestion");
    expect(within(ingestion).getByText("Unknown")).toBeTruthy();
    // The fleet list is unaffected by the failed probe.
    expect(screen.getByText("Honda Civic")).toBeTruthy();
  });

  it("never conflates API availability with database availability", async () => {
    databaseMock.mockRejectedValue(new ApiError(503, "db down"));

    renderWithProviders(<DashboardView />);

    const api = await screen.findByTestId("platform-api");
    const db = await screen.findByTestId("platform-db");
    expect(within(api).getByText("Available")).toBeTruthy();
    expect(within(db).getByText("Unavailable")).toBeTruthy();
  });

  it("links the active-simulators KPI to Simulation Control", async () => {
    overviewMock.mockResolvedValue(
      overview([vehicle()], { totals: totals({ vehicles: 1, active_simulations: 2 }) }),
    );

    renderWithProviders(<DashboardView />);

    const kpi = await screen.findByTestId("kpi-sims");
    expect(kpi.getAttribute("href")).toBe("/simulations");
  });

  it("does not fabricate a score when a vehicle has no assessment", async () => {
    overviewMock.mockResolvedValue(overview([vehicle()]));

    renderWithProviders(<DashboardView />);

    await screen.findByText("Honda Civic");
    expect(screen.getAllByText("Not assessed").length).toBeGreaterThan(0);
    expect(screen.queryByText(/\d+\/100/)).toBeNull();
  });

  it("masks the VIN in the fleet list", async () => {
    overviewMock.mockResolvedValue(overview([vehicle()]));

    renderWithProviders(<DashboardView />);

    await screen.findByText("Honda Civic");
    expect(screen.queryByText(TEST_VEHICLE.vin)).toBeNull();
    // Masked VIN keeps the first and last three characters.
    expect(screen.getByText(/^1HG\u2022+352$/)).toBeTruthy();
  });

  it("no longer duplicates the header destinations as Quick Action cards", async () => {
    overviewMock.mockResolvedValue(overview([vehicle()]));

    renderWithProviders(<DashboardView />);

    await screen.findByText("Honda Civic");
    // Simulation Control, Workflow Monitor and Knowledge Search now live in the
    // persistent top navigation, so the overview no longer repeats them.
    expect(screen.queryByRole("heading", { name: /quick actions/i })).toBeNull();
    expect(screen.queryByText("Quick actions")).toBeNull();
  });
});

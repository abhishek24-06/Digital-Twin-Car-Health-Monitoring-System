import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SimulationsView } from "@/components/simulations/simulations-view";
import { simulationsApi } from "@/services/simulations";
import { workflowApi } from "@/services/workflow";
import { ApiError } from "@/lib/api-error";
import {
  createWorkflowStreamHarness,
  renderWithProviders,
  TEST_VEHICLE,
} from "@/test/utils";
import type {
  PaginatedResponse,
  SimulationStatusResponse,
  WorkflowEventResponse,
} from "@/types/api";

const { vehiclesMock } = vi.hoisted(() => ({ vehiclesMock: vi.fn() }));

vi.mock("@/hooks/use-vehicle-data", async () => {
  const actual = await vi.importActual<
    typeof import("@/hooks/use-vehicle-data")
  >("@/hooks/use-vehicle-data");
  return {
    ...actual,
    useVehicles: () => vehiclesMock(),
  };
});

vi.mock("@/services/simulations", () => ({
  simulationsApi: {
    list: vi.fn(),
    status: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    restart: vi.fn(),
  },
}));

vi.mock("@/services/workflow", async () => {
  const actual = await vi.importActual<
    typeof import("@/services/workflow")
  >("@/services/workflow");
  return {
    ...actual,
    workflowApi: { ...actual.workflowApi, getState: vi.fn() },
  };
});

function list(vehicles: SimulationStatusResponse[]): PaginatedResponse<SimulationStatusResponse> {
  return { items: vehicles, page: 1, page_size: 100, total: vehicles.length };
}

function stopped(): SimulationStatusResponse {
  return {
    vehicle_id: TEST_VEHICLE.id,
    status: "stopped",
    scenario: null,
    interval_seconds: null,
    seed: null,
    started_at: null,
    error: null,
    last_telemetry_at: null,
  };
}

function running(overrides: Partial<SimulationStatusResponse> = {}): SimulationStatusResponse {
  return {
    vehicle_id: TEST_VEHICLE.id,
    status: "running",
    scenario: "high_temperature",
    interval_seconds: 1.5,
    seed: 42,
    started_at: "2026-01-01T10:00:00Z",
    error: null,
    last_telemetry_at: new Date().toISOString(),
    ...overrides,
  };
}

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

beforeEach(() => {
  vehiclesMock.mockReturnValue({
    data: [TEST_VEHICLE],
    isPending: false,
    isError: false,
    error: null,
    refetch: () => {},
  });
  vi.mocked(simulationsApi.list).mockResolvedValue(list([]));
  vi.mocked(workflowApi.getState).mockResolvedValue({ items: [] });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("SimulationsView", () => {
  it("shows vehicles by human-readable name and never renders a UUID", async () => {
    vi.mocked(simulationsApi.list).mockResolvedValue(list([stopped()]));

    renderWithProviders(<SimulationsView />);

    expect(await screen.findByText("Honda Civic")).toBeTruthy();
    expect(screen.getByText("2019 · 1.5L Turbo")).toBeTruthy();
    expect(screen.getByText("stopped")).toBeTruthy();
    expect(screen.queryByText(UUID_RE)).toBeNull();
  });

  it("starts a simulator with the chosen scenario and interval", async () => {
    const user = userEvent.setup();
    vi.mocked(simulationsApi.list)
      .mockResolvedValueOnce(list([stopped()]))
      .mockResolvedValue(list([running({ scenario: "normal", interval_seconds: 1 })]));
    vi.mocked(simulationsApi.start).mockResolvedValue(
      running({ scenario: "normal", interval_seconds: 1 }),
    );

    renderWithProviders(<SimulationsView />);

    await user.click(await screen.findByRole("button", { name: /^start$/i }));

    expect(simulationsApi.start).toHaveBeenCalledWith(TEST_VEHICLE.id, {
      scenario: "normal",
      interval_seconds: 1,
    });
    expect(await screen.findByText(/^running$/i)).toBeTruthy();
  });

  it("stops a running simulator and reflects the stopped state", async () => {
    const user = userEvent.setup();
    vi.mocked(simulationsApi.list)
      .mockResolvedValueOnce(list([running()]))
      .mockResolvedValue(list([stopped()]));
    vi.mocked(simulationsApi.stop).mockResolvedValue(stopped());

    renderWithProviders(<SimulationsView />);

    await user.click(await screen.findByRole("button", { name: /^stop$/i }));

    expect(simulationsApi.stop).toHaveBeenCalledWith(TEST_VEHICLE.id);
    expect(await screen.findByText(/^stopped$/i)).toBeTruthy();
  });

  it("maps a 409 conflict to an actionable message", async () => {
    const user = userEvent.setup();
    vi.mocked(simulationsApi.list).mockResolvedValue(list([running()]));
    vi.mocked(simulationsApi.restart).mockRejectedValue(new ApiError(409, "conflict"));

    renderWithProviders(<SimulationsView />);

    // The card is running, so Start is disabled; use Restart to exercise 409.
    await user.click(await screen.findByRole("button", { name: /^restart$/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/already running/i),
    );
  });

  it("maps a 502 spawn failure to a launcher message", async () => {
    const user = userEvent.setup();
    vi.mocked(simulationsApi.list).mockResolvedValue(list([stopped()]));
    vi.mocked(simulationsApi.start).mockRejectedValue(
      new ApiError(502, "Failed to start the simulator: the backend could not launch the simulator process."),
    );

    renderWithProviders(<SimulationsView />);

    await user.click(await screen.findByRole("button", { name: /^start$/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/could not launch/i),
    );
  });

  it("flags a degraded simulator with the backend's reason", async () => {
    vi.mocked(simulationsApi.list).mockResolvedValue(
      list([
        {
          ...running(),
          status: "degraded",
          error:
            "Simulator is running but the newest telemetry is from 2026-01-01T10:03:00Z -- the feed has gone stale. Check the MQTT broker and the backend subscriber.",
        },
      ]),
    );

    renderWithProviders(<SimulationsView />);

    expect(await screen.findByText(/^degraded$/i)).toBeTruthy();
    expect(screen.getByText(/feed has gone stale/i)).toBeTruthy();
    expect(screen.queryByText(/no recent telemetry/i)).toBeNull();
  });

  it("shows an empty state when there are no vehicles", async () => {
    vehiclesMock.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      error: null,
      refetch: () => {},
    });

    renderWithProviders(<SimulationsView />);

    expect(await screen.findByText("No vehicles registered")).toBeTruthy();
  });

  it("renders an errored simulator with its backend reason", async () => {
    vi.mocked(simulationsApi.list).mockResolvedValue(
      list([
        {
          ...stopped(),
          status: "error",
          error: "Simulator process exited unexpectedly (exit code 2)",
        },
      ]),
    );

    renderWithProviders(<SimulationsView />);

    expect(await screen.findByText(/Simulator failed/i)).toBeTruthy();
    expect(
      screen.getByText(/Simulator process exited unexpectedly/),
    ).toBeTruthy();
  });

  it("never leaks the vehicle id into the DOM even when statuses reference it", async () => {
    vi.mocked(simulationsApi.list).mockResolvedValue(
      list([running({ last_telemetry_at: null })]),
    );

    renderWithProviders(<SimulationsView />);

    await screen.findByText(/^running$/i);
    expect(screen.queryByText(UUID_RE)).toBeNull();
  });
});

const SECOND_VEHICLE = {
  ...TEST_VEHICLE,
  id: "33333333-3333-4333-8333-333333333333",
  vin: "1HGCM82633A009999",
  make: "Toyota",
  model: "Corolla",
};

function simulationEvent(
  overrides: Partial<WorkflowEventResponse> = {},
): WorkflowEventResponse {
  return {
    event_id: "sim-evt",
    timestamp: "2026-01-01T00:00:01Z",
    workflow: "simulation",
    stage: "simulation_started",
    status: "success",
    message: "Simulation started",
    vehicle_id: TEST_VEHICLE.id,
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

describe("SimulationsView contextual telemetry pipeline", () => {
  it("shows only a Ready affordance before the simulator starts", async () => {
    vi.mocked(simulationsApi.list).mockResolvedValue(list([stopped()]));

    renderWithProviders(<SimulationsView />);

    expect(await screen.findByTestId("simulation-ready")).toBeTruthy();
    expect(screen.queryByText("Telemetry Pipeline")).toBeNull();
  });

  it("reveals the telemetry pipeline once real activity arrives", async () => {
    vi.mocked(simulationsApi.list).mockResolvedValue(list([stopped()]));
    const harness = createWorkflowStreamHarness();

    renderWithProviders(<SimulationsView />, {
      eventSourceFactory: harness.factory,
    });

    await screen.findByTestId("simulation-ready");

    harness.latest().emit(simulationEvent({ vehicle_id: TEST_VEHICLE.id }));

    expect(await screen.findByText("Telemetry Pipeline")).toBeTruthy();
    expect(screen.queryByTestId("simulation-ready")).toBeNull();
  });

  it("renders a derived DEGRADED broker state honestly", async () => {
    vi.mocked(simulationsApi.list).mockResolvedValue(list([running()]));
    vi.mocked(workflowApi.getState).mockResolvedValue({
      items: [
        {
          vehicle_id: TEST_VEHICLE.id,
          simulation_status: "running",
          stages: [
            {
              stage: "mqtt_broker",
              status: "degraded",
              observation: "derived",
              at: null,
              detail: "No recent telemetry flow observed",
            },
          ],
          last_telemetry_at: null,
          messages_received: 0,
          snapshot_at: null,
          degraded_reason: null,
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    renderWithProviders(<SimulationsView />);

    expect(await screen.findByText("Degraded")).toBeTruthy();
    expect(screen.getByText("No recent telemetry flow observed")).toBeTruthy();
  });

  it("keeps pipelines isolated per vehicle", async () => {
    vehiclesMock.mockReturnValue({
      data: [TEST_VEHICLE, SECOND_VEHICLE],
      isPending: false,
      isError: false,
      error: null,
      refetch: () => {},
    });
    vi.mocked(simulationsApi.list).mockResolvedValue(
      list([
        stopped(),
        { ...stopped(), vehicle_id: SECOND_VEHICLE.id },
      ]),
    );
    const harness = createWorkflowStreamHarness();

    renderWithProviders(<SimulationsView />, {
      eventSourceFactory: harness.factory,
    });

    await screen.findByText("Honda Civic");
    expect(screen.getAllByTestId("simulation-ready")).toHaveLength(2);

    harness.latest().emit(simulationEvent({ vehicle_id: TEST_VEHICLE.id }));

    expect(await screen.findAllByText("Telemetry Pipeline")).toHaveLength(1);
    expect(screen.getAllByTestId("simulation-ready")).toHaveLength(1);
  });
});
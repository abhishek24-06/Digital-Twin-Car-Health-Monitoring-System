import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkflowView } from "@/components/workflow/workflow-view";
import { workflowApi } from "@/services/workflow";
import { createWorkflowStreamHarness, renderWithProviders } from "@/test/utils";
import type { WorkflowEventResponse, WorkflowStatusResponse } from "@/types/api";

vi.mock("@/services/workflow", async () => {
  const actual = await vi.importActual<typeof import("@/services/workflow")>(
    "@/services/workflow",
  );
  return {
    ...actual,
    workflowApi: { ...actual.workflowApi, getWorkflowStatus: vi.fn() },
  };
});

const STATUS: WorkflowStatusResponse = {
  telemetry_pipeline_active: false,
  rag_pipeline_active: false,
  agent_pipeline_active: false,
  subscriber_running: false,
  active_simulations: 0,
  events_in_buffer: 0,
  oldest_event_ts: null,
  newest_event_ts: null,
};

function event(
  overrides: Partial<WorkflowEventResponse> = {},
): WorkflowEventResponse {
  return {
    event_id: "e1",
    timestamp: new Date().toISOString(),
    workflow: "telemetry",
    stage: "telemetry_persisted",
    status: "success",
    message: "Telemetry persisted",
    vehicle_id: null,
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

describe("WorkflowView monitor controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(workflowApi.getWorkflowStatus).mockResolvedValue(STATUS);
  });

  afterEach(() => vi.restoreAllMocks());

  it("narrows the timeline when a workflow filter is chosen", async () => {
    const user = userEvent.setup();
    const harness = createWorkflowStreamHarness();
    renderWithProviders(<WorkflowView />, {
      eventSourceFactory: harness.factory,
    });
    harness.latest().open();
    harness.latest().emit(event({ event_id: "t", message: "Telemetry boom" }));
    harness.latest().emit(
      event({
        event_id: "r",
        workflow: "rag_query",
        stage: "query_received",
        message: "Query boom",
      }),
    );

    expect(await screen.findByText("Telemetry boom")).toBeTruthy();
    expect(screen.getByText("Query boom")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /filter by workflow/i }));
    await user.click(screen.getByRole("button", { name: "rag_query" }));

    expect(screen.queryByText("Telemetry boom")).toBeNull();
    expect(screen.getByText("Query boom")).toBeTruthy();
  });

  it("pauses and resumes the view", async () => {
    const user = userEvent.setup();
    const harness = createWorkflowStreamHarness();
    renderWithProviders(<WorkflowView />, {
      eventSourceFactory: harness.factory,
    });
    harness.latest().open();
    harness.latest().emit(event({ event_id: "a", message: "First event" }));
    expect(await screen.findByText("First event")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /^pause$/i }));
    harness.latest().emit(event({ event_id: "b", message: "Second event" }));
    expect(screen.queryByText("Second event")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^resume$/i }));
    expect(await screen.findByText("Second event")).toBeTruthy();
  });

  it("clears the timeline", async () => {
    const user = userEvent.setup();
    const harness = createWorkflowStreamHarness();
    renderWithProviders(<WorkflowView />, {
      eventSourceFactory: harness.factory,
    });
    harness.latest().open();
    harness.latest().emit(event({ message: "Clearable event" }));
    expect(await screen.findByText("Clearable event")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /^clear$/i }));
    expect(screen.queryByText("Clearable event")).toBeNull();
  });

  it("renders Simulation and System tabs and their events", async () => {
    const user = userEvent.setup();
    const harness = createWorkflowStreamHarness();
    renderWithProviders(<WorkflowView />, {
      eventSourceFactory: harness.factory,
    });
    harness.latest().open();
    harness.latest().emit(
      event({
        event_id: "s",
        workflow: "simulation",
        stage: "simulation_started",
        message: "Sim started",
      }),
    );
    harness.latest().emit(
      event({
        event_id: "y",
        workflow: "system",
        stage: "subscriber_started",
        message: "Subscriber up",
      }),
    );

    await user.click(screen.getByRole("tab", { name: "Simulation" }));
    expect(screen.getByText("Simulation events")).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: "System" }));
    expect(screen.getByText("System events")).toBeTruthy();
  });

  it("filters the timeline by correlation id", async () => {
    const user = userEvent.setup();
    const harness = createWorkflowStreamHarness();
    renderWithProviders(<WorkflowView />, {
      eventSourceFactory: harness.factory,
    });
    harness.latest().open();
    harness.latest().emit(
      event({ event_id: "c1", correlation_id: "corr-1", message: "Corr one" }),
    );
    harness.latest().emit(
      event({ event_id: "c2", correlation_id: "corr-2", message: "Corr two" }),
    );

    await user.type(screen.getByLabelText("Correlation id"), "corr-1");

    expect(screen.getByText("Corr one")).toBeTruthy();
    expect(screen.queryByText("Corr two")).toBeNull();
  });
});

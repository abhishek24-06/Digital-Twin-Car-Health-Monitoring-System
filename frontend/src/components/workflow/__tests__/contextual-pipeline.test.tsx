import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContextualPipeline } from "@/components/workflow/contextual-pipeline";
import {
  WorkflowStreamProvider,
  type WorkflowEventSourceLike,
} from "@/components/workflow/workflow-stream-provider";
import type { VehicleTelemetryState, WorkflowEventResponse } from "@/types/api";

class FakeEventSource implements WorkflowEventSourceLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close(): void {}
}

function factory(log: FakeEventSource[]) {
  return () => {
    const source = new FakeEventSource();
    log.push(source);
    return source;
  };
}

function open(source: FakeEventSource) {
  act(() => source.onopen?.(new Event("open")));
}

function dispatch(source: FakeEventSource, payload: WorkflowEventResponse) {
  act(() => source.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent));
}

function event(overrides: Partial<WorkflowEventResponse> = {}): WorkflowEventResponse {
  return {
    event_id: "e1",
    timestamp: "2026-01-01T00:00:00Z",
    workflow: "agent",
    stage: "agent_request_received",
    status: "running",
    message: "m",
    vehicle_id: null,
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

function renderPipeline(node: React.ReactNode) {
  const log: FakeEventSource[] = [];
  render(
    <WorkflowStreamProvider eventSourceFactory={factory(log)} reconnectDelays={[1, 2, 4]}>
      {node}
    </WorkflowStreamProvider>,
  );
  open(log[0]);
  return log;
}

describe("ContextualPipeline", () => {
  it("renders registry stages only once a matching event arrives", () => {
    const log = renderPipeline(<ContextualPipeline id="agent" />);

    expect(screen.queryByText("Agent Request Received")).toBeNull();

    dispatch(
      log[0],
      event({ stage: "agent_request_received", status: "running" }),
    );

    expect(screen.getByText("Agent Request Received")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("ignores out-of-scope workflow events", () => {
    const log = renderPipeline(<ContextualPipeline id="agent" />);
    dispatch(log[0], event({ event_id: "a", stage: "agent_request_received" }));

    dispatch(
      log[0],
      event({
        event_id: "b",
        workflow: "rag_query",
        stage: "query_received",
        status: "success",
      }),
    );

    expect(screen.getByText("Agent Request Received")).toBeInTheDocument();
    expect(screen.queryByText("Query Received")).toBeNull();
    expect(screen.queryByText("Success")).toBeNull();
  });

  it("overlays a derived telemetry state (honest provenance)", () => {
    const derived: VehicleTelemetryState = {
      vehicle_id: "v1",
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
    };

    renderPipeline(<ContextualPipeline id="telemetry" derivedState={derived} />);

    expect(screen.getByText("MQTT Broker")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(
      screen.getByText("No recent telemetry flow observed"),
    ).toBeInTheDocument();
  });
});

import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  WorkflowStreamProvider,
  useWorkflowConnection,
  useWorkflowSlice,
  type WorkflowEventSourceLike,
} from "@/components/workflow/workflow-stream-provider";
import type { WorkflowEventResponse } from "@/types/api";

class FakeEventSource implements WorkflowEventSourceLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = 0;

  constructor(public readonly url = "/api/workflow/events/stream") {}

  close(): void {
    this.closed += 1;
  }
}

function makeFactory(log: FakeEventSource[]) {
  return () => {
    const source = new FakeEventSource();
    log.push(source);
    return source;
  };
}

function open(source: FakeEventSource) {
  act(() => {
    source.onopen?.(new Event("open"));
  });
}

function dispatch(source: FakeEventSource, payload: WorkflowEventResponse) {
  act(() => {
    source.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  });
}

function dispatchError(source: FakeEventSource) {
  act(() => {
    source.onerror?.(new Event("error"));
  });
}

function event(overrides: Partial<WorkflowEventResponse> = {}): WorkflowEventResponse {
  return {
    event_id: "e1",
    timestamp: "2026-01-01T00:00:00Z",
    workflow: "simulation",
    stage: "simulation_started",
    status: "success",
    message: "m",
    vehicle_id: null,
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

function ConnectionProbe() {
  const connection = useWorkflowConnection();
  return <span data-testid="connection">{connection}</span>;
}

function SliceProbe({ vehicleId }: { vehicleId?: string }) {
  const { events } = useWorkflowSlice(vehicleId ? { vehicleId } : {});
  return <span data-testid="count">{events.length}</span>;
}

const RECONNECT_FAST = [1, 2, 4];

function renderProvider(log: FakeEventSource[], children: React.ReactNode) {
  return render(
    <WorkflowStreamProvider
      eventSourceFactory={makeFactory(log)}
      reconnectDelays={RECONNECT_FAST}
    >
      {children}
    </WorkflowStreamProvider>,
  );
}

describe("WorkflowStreamProvider", () => {
  it("mounts exactly one EventSource", () => {
    const log: FakeEventSource[] = [];
    renderProvider(log, <SliceProbe />);
    expect(log).toHaveLength(1);
  });

  it("shares a single EventSource between many consumers", () => {
    const log: FakeEventSource[] = [];
    renderProvider(
      log,
      <>
        <SliceProbe />
        <SliceProbe vehicleId="v1" />
        <ConnectionProbe />
      </>,
    );
    expect(log).toHaveLength(1);
  });

  it("transitions connecting -> live -> reconnecting -> live over one drop", async () => {
    const log: FakeEventSource[] = [];
    renderProvider(log, <ConnectionProbe />);

    expect(screen.getByTestId("connection").textContent).toBe("connecting");

    open(log[0]);
    expect(screen.getByTestId("connection").textContent).toBe("live");

    dispatchError(log[0]);
    expect(screen.getByTestId("connection").textContent).toBe("reconnecting");

    await waitFor(() => expect(log).toHaveLength(2));
    expect(log[0].closed).toBeGreaterThan(0);

    open(log[1]);
    await waitFor(() =>
      expect(screen.getByTestId("connection").textContent).toBe("live"),
    );
  });

  it("closes the source and cancels a pending reconnect on unmount", async () => {
    const log: FakeEventSource[] = [];
    const { unmount } = renderProvider(log, <ConnectionProbe />);

    open(log[0]);
    dispatchError(log[0]);
    unmount();

    await new Promise((resolve) => setTimeout(resolve, 25));

    expect(log).toHaveLength(1);
    expect(log[0].closed).toBeGreaterThan(0);
  });

  it("scopes events per consumer", () => {
    const log: FakeEventSource[] = [];
    renderProvider(log, <SliceProbe vehicleId="v1" />);

    open(log[0]);
    dispatch(log[0], event({ event_id: "a", vehicle_id: "v1" }));
    dispatch(log[0], event({ event_id: "b", vehicle_id: "v2" }));

    expect(screen.getByTestId("count").textContent).toBe("1");
  });

  it("dedupes events by event_id", () => {
    const log: FakeEventSource[] = [];
    renderProvider(log, <SliceProbe />);

    open(log[0]);
    dispatch(log[0], event({ event_id: "a" }));
    dispatch(log[0], event({ event_id: "a" }));

    expect(screen.getByTestId("count").textContent).toBe("1");
  });
});

import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveTelemetryFeed } from "@/components/telemetry/live-telemetry-feed";
import type { TelemetryEventSourceLike } from "@/lib/telemetry-stream";
import { telemetryApi } from "@/services/vehicles";
import { TEST_VEHICLE } from "@/test/utils";
import type { TelemetryResponse, TelemetryStreamPayload } from "@/types/api";

class FakeEventSource implements TelemetryEventSourceLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readonly readyState = 0;
  closed = 0;

  constructor(public readonly url: string) {}

  close(): void {
    this.closed += 1;
  }
}

function makeSample(overrides: Partial<TelemetryResponse> = {}): TelemetryResponse {
  return {
    id: "90000000-0000-4000-8000-000000000001",
    vehicle_id: TEST_VEHICLE.id,
    timestamp: new Date().toISOString(),
    rpm: 3200,
    speed: 88,
    engine_load: 42,
    coolant_temperature: 91,
    oil_temperature: 98,
    battery_voltage: 14.2,
    fuel_level: 61,
    intake_air_temperature: 34,
    throttle_position: 27,
    engine_runtime: 5200,
    odometer: 81234,
    raw_payload: null,
    source_event_id: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function frame(
  events: TelemetryResponse[],
  timestamp = new Date().toISOString(),
): TelemetryStreamPayload {
  return { timestamp, server_time: timestamp, events };
}

function liveFeedWith(events: FakeEventSource[]) {
  const factory = (url: string) => {
    const source = new FakeEventSource(url);
    events.push(source);
    return source;
  };
  const utils = render(<LiveTelemetryFeed vehicleId={TEST_VEHICLE.id} eventSourceFactory={factory} />);
  return { ...utils, source: events[0] };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LiveTelemetryFeed", () => {
  it("shows an inactive state when no vehicle is selected", () => {
    render(<LiveTelemetryFeed vehicleId="" />);
    expect(screen.getByText(/Select a vehicle to begin streaming/i)).toBeInTheDocument();
    expect(screen.getByText("Off")).toBeInTheDocument();
  });

  it("displays streamed samples with a live badge", async () => {
    const log: FakeEventSource[] = [];
    const { source } = liveFeedWith(log);

    act(() => {
      source.onopen?.(new Event("open"));
      source.onmessage?.({ data: JSON.stringify(frame([makeSample()])) });
    });

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.getByText("3200.00")).toBeInTheDocument();
    expect(screen.getByText("14.2")).toBeInTheDocument();
    expect(screen.queryByText(/Polling fallback/i)).not.toBeInTheDocument();
  });

  it("flags stale data when no new frame has arrived on an open stream", () => {
    const log: FakeEventSource[] = [];
    const { source } = liveFeedWith(log);

    const staleAt = new Date(Date.now() - 30_000).toISOString();
    act(() => {
      source.onopen?.(new Event("open"));
      source.onmessage?.({ data: JSON.stringify(frame([makeSample({ timestamp: staleAt })], staleAt)) });
    });

    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText(/No new frames for a while/i)).toBeInTheDocument();
  });

  it("falls back to polling the telemetry endpoint when the stream drops", async () => {
    const polled = makeSample({ id: "90000000-0000-4000-8000-000000000099", rpm: 5555 });
    vi.spyOn(telemetryApi, "list").mockResolvedValue({
      items: [polled],
      page: 1,
      page_size: 1,
      total: 1,
    });

    const log: FakeEventSource[] = [];
    const { source } = liveFeedWith(log);

    act(() => {
      source.onopen?.(new Event("open"));
      source.onerror?.(new Event("error"));
    });

    await waitFor(() => expect(screen.getByText(/Polling fallback/i)).toBeInTheDocument());
    expect(telemetryApi.list).toHaveBeenCalledWith(
      TEST_VEHICLE.id,
      { pageSize: 1 },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("5555.00")).toBeInTheDocument();
  });
});
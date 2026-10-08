import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useTelemetryStream } from "@/hooks/use-telemetry-stream";
import {
  TELEMETRY_STREAM_POLL_SECONDS,
  type TelemetryEventSourceLike,
} from "@/lib/telemetry-stream";
import { TEST_VEHICLE } from "@/test/utils";
import type { TelemetryResponse, TelemetryStreamPayload } from "@/types/api";

const STREAM_URL = `/api/vehicles/${TEST_VEHICLE.id}/telemetry/stream?interval_seconds=${TELEMETRY_STREAM_POLL_SECONDS}`;

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

function makeFactory(log: FakeEventSource[]) {
  return (url: string) => {
    const source = new FakeEventSource(url);
    log.push(source);
    return source;
  };
}

function makeEvent(id: string, timestamp = `2026-01-01T00:00:0${id.slice(-1)}Z`): TelemetryResponse {
  return {
    id,
    vehicle_id: TEST_VEHICLE.id,
    timestamp,
    rpm: null,
    speed: null,
    engine_load: null,
    coolant_temperature: null,
    oil_temperature: null,
    battery_voltage: null,
    fuel_level: null,
    intake_air_temperature: null,
    throttle_position: null,
    engine_runtime: null,
    odometer: null,
    raw_payload: null,
    source_event_id: null,
    created_at: timestamp,
  };
}

function frame(events: TelemetryResponse[], timestamp = "2026-01-01T01:00:00Z"): TelemetryStreamPayload {
  return { timestamp, server_time: timestamp, events };
}

function open(source: FakeEventSource) {
  act(() => {
    source.onopen?.(new Event("open"));
  });
}

function dispatchMessage(source: FakeEventSource, payload: TelemetryStreamPayload) {
  act(() => {
    source.onmessage?.({ data: JSON.stringify(payload) });
  });
}

function dispatchError(source: FakeEventSource) {
  act(() => {
    source.onerror?.(new Event("error"));
  });
}

const RECONNECT_FAST = [1, 2, 4] as const;

describe("useTelemetryStream", () => {
  it("creates a connection at the stream URL and transitions to open", () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, { eventSourceFactory: factory }),
    );

    expect(log).toHaveLength(1);
    expect(log[0].url).toBe(STREAM_URL);
    expect(result.current.status).toBe("connecting");

    open(log[0]);
    expect(result.current.status).toBe("open");
    expect(result.current.error).toBeNull();
    expect(log).toHaveLength(1);
  });

  it("stays idle when no vehicle is selected", () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(null, { eventSourceFactory: factory }),
    );

    expect(log).toHaveLength(0);
    expect(result.current.status).toBe("idle");
  });

  it("prepends streamed samples newest-first and keeps the buffer bounded", async () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, {
        maxSamples: 2,
        eventSourceFactory: factory,
      }),
    );

    open(log[0]);
    dispatchMessage(
      log[0],
      frame([makeEvent("a", "2026-01-01T00:00:01Z"), makeEvent("b", "2026-01-01T00:00:02Z")]),
    );
    dispatchMessage(
      log[0],
      frame([makeEvent("c", "2026-01-01T00:00:03Z")], "2026-01-01T00:00:03Z"),
    );

    await waitFor(() => expect(result.current.samples.length).toBe(2));
    expect(result.current.samples.map((sample) => sample.id)).toEqual(["c", "b"]);
    expect(result.current.lastEventAt).toBe("2026-01-01T00:00:03Z");
  });

  it("dedupes overlapping batches by sample id", async () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, {
        maxSamples: 10,
        eventSourceFactory: factory,
      }),
    );

    open(log[0]);
    dispatchMessage(log[0], frame([makeEvent("a")]));
    dispatchMessage(
      log[0],
      frame([makeEvent("a"), makeEvent("b", "2026-01-01T00:00:02Z")]),
    );

    await waitFor(() => expect(result.current.samples).toHaveLength(2));
    expect(result.current.samples.map((sample) => sample.id)).toEqual(["b", "a"]);
  });

  it("ignores heartbeats and malformed frames without changing state", async () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, { eventSourceFactory: factory }),
    );

    open(log[0]);
    dispatchMessage(log[0], frame([makeEvent("a")]));
    await waitFor(() => expect(result.current.samples).toHaveLength(1));

    act(() => {
      log[0].onmessage?.({ data: "not json" });
      log[0].onmessage?.({ data: JSON.stringify({ timestamp: "x" }) });
    });

    expect(result.current.samples).toHaveLength(1);
    expect(result.current.status).toBe("open");
  });

  it("reconnects after a drop with backoff and recovers on the next open", async () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, {
        reconnectDelays: RECONNECT_FAST,
        eventSourceFactory: factory,
      }),
    );

    open(log[0]);
    dispatchError(log[0]);

    expect(result.current.status).toBe("reconnecting");

    await waitFor(() => expect(log).toHaveLength(2));
    expect(log[0].closed).toBeGreaterThan(0);

    open(log[1]);
    dispatchMessage(log[1], frame([makeEvent("a")]));

    await waitFor(() => expect(result.current.status).toBe("open"));
    expect(result.current.samples.map((sample) => sample.id)).toEqual(["a"]);
  });

  it("grows the backoff ladder on repeated failures", async () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, {
        reconnectDelays: RECONNECT_FAST,
        eventSourceFactory: factory,
      }),
    );

    open(log[0]);
    dispatchError(log[0]);
    await waitFor(() => expect(log).toHaveLength(2));

    open(log[1]);
    dispatchError(log[1]);
    await waitFor(() => expect(log).toHaveLength(3));

    expect(result.current.status).toBe("reconnecting");
    expect(log[1].closed).toBeGreaterThan(0);
  });

  it("terminates in error state when reconnection is disabled", () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, {
        reconnectDelays: [],
        eventSourceFactory: factory,
      }),
    );

    open(log[0]);
    dispatchError(log[0]);

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("Live connection dropped.");
    expect(log).toHaveLength(1);
  });

  it("closes the source and cancels a pending reconnect on unmount", async () => {
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { unmount } = renderHook(() =>
      useTelemetryStream(TEST_VEHICLE.id, {
        reconnectDelays: RECONNECT_FAST,
        eventSourceFactory: factory,
      }),
    );

    open(log[0]);
    dispatchError(log[0]);

    unmount();
    await new Promise((resolve) => setTimeout(resolve, 25));

    expect(log).toHaveLength(1);
    expect(log[0].closed).toBeGreaterThan(0);
  });

  it("tears down and re-creates the stream when the vehicle changes", async () => {
    const otherId = "33333333-3333-4333-8333-333333333333";
    const log: FakeEventSource[] = [];
    const factory = makeFactory(log);
    const { result, rerender } = renderHook(
      ({ vehicleId }: { vehicleId: string | null }) =>
        useTelemetryStream(vehicleId, { eventSourceFactory: factory }),
      { initialProps: { vehicleId: TEST_VEHICLE.id } },
    );

    expect(log).toHaveLength(1);

    rerender({ vehicleId: otherId });

    await waitFor(() => expect(log).toHaveLength(2));
    expect(log[0].closed).toBeGreaterThan(0);
    expect(log[1].url).toContain(`/api/vehicles/${otherId}/telemetry/stream`);
    expect(result.current.status).toBe("connecting");

    open(log[1]);
    await waitFor(() => expect(result.current.status).toBe("open"));
  });
});
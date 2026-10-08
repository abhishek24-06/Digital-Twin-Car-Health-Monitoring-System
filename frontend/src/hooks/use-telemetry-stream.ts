"use client";

import * as React from "react";
import {
  createTelemetryEventSource,
  parseTelemetryStreamPayload,
  telemetryStreamUrl,
  type TelemetryEventSourceLike,
} from "@/lib/telemetry-stream";
import type { TelemetryResponse } from "@/types/api";

export type TelemetryStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "error";

export interface TelemetryStreamState {
  status: TelemetryStreamStatus;
  /** Streamed samples, newest first, deduped, capped at `maxSamples`. */
  samples: readonly TelemetryResponse[];
  /** Backend frame timestamp of the most recent frame that carried events. */
  lastEventAt: string | null;
  /** Human-readable reason set when the stream terminally fails. */
  error: string | null;
}

const DEFAULT_MAX_SAMPLES = 200;

const EMPTY_SAMPLES: readonly TelemetryResponse[] = [];

/** Reconnect backoff ladder, ms. The final entry is reused until it reconnects. */
export const DEFAULT_RECONNECT_DELAYS = [1_000, 2_500, 5_000, 10_000, 15_000] as const;

export interface UseTelemetryStreamOptions {
  maxSamples?: number;
  /**
   * Mandatory delay between reconnects, ms. Pass `[]` to disable reconnects; a
   * dropped connection then flips the status to `error`.
   */
  reconnectDelays?: readonly number[];
  /** Injectable `EventSource` factory so tests can drive the stream manually. */
  eventSourceFactory?: (url: string) => TelemetryEventSourceLike;
}

/**
 * Live consume the vehicle telemetry SSE stream.
 *
 * The connection is owned by this hook: it is created when a `vehicleId` is
 * provided, torn down on unmount or `vehicleId` change, and re-established
 * with an exponential backoff ladder when the server drops it.
 */
export function useTelemetryStream(
  vehicleId: string | null | undefined,
  options: UseTelemetryStreamOptions = {},
): TelemetryStreamState {
  const {
    maxSamples = DEFAULT_MAX_SAMPLES,
    reconnectDelays = DEFAULT_RECONNECT_DELAYS,
    eventSourceFactory,
  } = options;

  const [status, setStatus] = React.useState<TelemetryStreamStatus>("idle");
  const [samples, setSamples] = React.useState<TelemetryResponse[]>([]);
  const [lastEventAt, setLastEventAt] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  /**
   * The backoff ladder is read on every reconnect attempt, so keep it in a ref:
   * callers often pass an inline (or defaulted) array, and re-running the whole
   * stream effect on an identity change would tear the connection down.
   */
  const reconnectDelaysRef = React.useRef(reconnectDelays);
  React.useEffect(() => {
    reconnectDelaysRef.current = reconnectDelays;
  });

  /**
   * Which vehicle the buffered samples belong to. Cleared when a new stream
   * effect starts; the first `open`/`message` of that stream wipes any
   * leftover buffer from a previously selected vehicle.
   */
  const bufferVehicle = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (!vehicleId) return;

    let disposed = false;
    let attempt = 0;
    let source: TelemetryEventSourceLike | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    bufferVehicle.current = null;

    const clearTimer = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const connect = () => {
      if (disposed) return;
      setError(null);
      setStatus(attempt === 0 ? "connecting" : "reconnecting");

      const next = (eventSourceFactory ?? createTelemetryEventSource)(
        telemetryStreamUrl(vehicleId),
      );
      source = next;

      next.onopen = () => {
        if (disposed || source !== next) return;
        if (bufferVehicle.current !== vehicleId) {
          bufferVehicle.current = vehicleId;
          setSamples([]);
          setLastEventAt(null);
        }
        attempt = 0;
        setError(null);
        setStatus("open");
      };

      next.onmessage = (event) => {
        if (disposed || source !== next) return;
        if (typeof event.data !== "string") return;
        const payload = parseTelemetryStreamPayload(event.data);
        if (!payload) return;

        if (bufferVehicle.current !== vehicleId) {
          bufferVehicle.current = vehicleId;
          setSamples([]);
        }
        setSamples((current) => {
          const seen = new Set<string>(current.map((sample) => sample.id));
          const fresh = payload.events.filter((sample) => !seen.has(sample.id));
          if (fresh.length === 0) return current;
          // The backend emits samples ascending in time; newest-first overall.
          return [...fresh.reverse(), ...current].slice(0, maxSamples);
        });
        setLastEventAt(payload.timestamp);
      };

      next.onerror = () => {
        if (disposed || source !== next) return;
        next.close();
        source = null;

        const delays = reconnectDelaysRef.current;
        if (delays.length === 0) {
          setError("Live connection dropped.");
          setStatus("error");
          return;
        }

        const delay = delays[Math.min(attempt, delays.length - 1)];
        attempt += 1;
        setStatus("reconnecting");
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      disposed = true;
      clearTimer();
      if (source) source.close();
      source = null;
    };
  }, [vehicleId, eventSourceFactory, maxSamples]);

  const isActive = Boolean(vehicleId);
  return {
    status: isActive ? status : "idle",
    samples: isActive ? samples : EMPTY_SAMPLES,
    lastEventAt: isActive ? lastEventAt : null,
    error: isActive ? error : null,
  };
}
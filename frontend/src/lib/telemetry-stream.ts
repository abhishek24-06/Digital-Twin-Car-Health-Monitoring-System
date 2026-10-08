/**
 * Live telemetry streaming (client side).
 *
 * The backend stream requires a bearer token, which native `EventSource` cannot
 * attach (and which never lives in a cookie the browser would send to the
 * backend). The client therefore connects to a same-origin Next.js proxy route
 * (`/api/vehicles/{id}/telemetry/stream`), and that proxy adds the token from
 * the httpOnly session cookies and pipes the upstream SSE body through.
 */

import type { TelemetryStreamPayload } from "@/types/api";

/** Mirrors the backend's default `telemetry_stream_poll_seconds`. */
export const TELEMETRY_STREAM_POLL_SECONDS = 1;

export function telemetryStreamUrl(vehicleId: string): string {
  return `/api/vehicles/${encodeURIComponent(vehicleId)}/telemetry/stream?interval_seconds=${TELEMETRY_STREAM_POLL_SECONDS}`;
}

/**
 * Minimal structural shape the hook relies on, so tests can inject a fake and
 * the real `EventSource` satisfies it (its `addEventListener`/`onerror`
 * handlers are both present, but only the `on*` trio is used).
 */
export interface TelemetryEventSourceLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onerror: ((event: Event) => void) | null;
  close: () => void;
  readonly readyState: number;
}

export function createTelemetryEventSource(url: string): TelemetryEventSourceLike {
  // The native type's `onmessage` is typed against `MessageEvent`; ours only
  // narrows it to `{ data: string }`, which is all the hook ever reads.
  return new EventSource(url) as unknown as TelemetryEventSourceLike;
}

/**
 * Parse one SSE `data:` line into a stream payload. Returns `null` for
 * heartbeats (no `data:` line), non-object bodies, or malformed shapes.
 */
export function parseTelemetryStreamPayload(data: string): TelemetryStreamPayload | null {
  if (!data) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const candidate = parsed as Partial<TelemetryStreamPayload>;
  if (!Array.isArray(candidate.events) || typeof candidate.timestamp !== "string") {
    return null;
  }
  return {
    timestamp: candidate.timestamp,
    server_time:
      typeof candidate.server_time === "string" ? candidate.server_time : candidate.timestamp,
    events: candidate.events,
  };
}
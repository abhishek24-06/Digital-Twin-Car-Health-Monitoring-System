import { NextResponse, type NextRequest } from "next/server";
import {
  backendBaseUrl,
  readAccessToken,
  refreshAccessToken,
} from "@/lib/session-server";

/**
 * `GET /api/vehicles/{vehicleId}/telemetry/stream`
 *
 * Server-side proxy for the backend SSE endpoint. `EventSource` cannot attach
 * an `Authorization` header, and the bearer token never lives somewhere the
 * browser would send to the backend, so this route:
 *
 * 1. reads the access token from the httpOnly session cookie;
 * 2. opens the upstream stream with the bearer token and pipes the SSE body
 *    straight back (heartbeats included);
 * 3. on a 401 from the backend, rotates the refresh token once and retries;
 * 4. on a missing/expired session, returns 401 and lets the client's re-live
 *    backoff driver surface the "sign in" state elsewhere.
 */
export const dynamic = "force-dynamic";

interface StreamResult {
  status: number;
  body: ReadableStream<Uint8Array> | null;
  bodyText: string | null;
  contentType: string;
}

async function openBackendStream(vehicleId: string, accessToken: string): Promise<StreamResult> {
  const response = await fetch(
    `${backendBaseUrl()}/vehicles/${vehicleId}/telemetry/stream`,
    {
      headers: {
        Accept: "text/event-stream",
        Authorization: `Bearer ${accessToken}`,
      },
      cache: "no-store",
    },
  );
  const body = response.body;
  if (body) {
    return {
      status: response.status,
      body,
      bodyText: null,
      contentType: response.headers.get("content-type") ?? "text/event-stream",
    };
  }
  return {
    status: response.status,
    body: null,
    bodyText: await response.text(),
    contentType: response.headers.get("content-type") ?? "application/json",
  };
}

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ vehicleId: string }> },
): Promise<Response> {
  const { vehicleId } = await context.params;

  let accessToken = await readAccessToken();
  if (!accessToken) accessToken = await refreshAccessToken();
  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  let stream = await openBackendStream(vehicleId, accessToken);
  if (stream.status === 401) {
    // Expired underneath us: rotate once and retry a single time.
    const rotated = await refreshAccessToken();
    if (!rotated) {
      return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
    }
    stream = await openBackendStream(vehicleId, rotated);
  }

  if (stream.status !== 200 || !stream.body) {
    return new NextResponse(stream.bodyText ?? "Upstream error", {
      status: stream.status,
      headers: { "Content-Type": stream.contentType },
    });
  }

  return new Response(stream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
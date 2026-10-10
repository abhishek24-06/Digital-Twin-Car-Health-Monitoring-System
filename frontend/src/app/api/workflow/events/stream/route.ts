import { NextRequest, NextResponse } from "next/server";
import { readAccessToken } from "@/lib/session-server";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ?? "http://localhost:8000/api/v1";

export async function GET(request: NextRequest) {
  // Get the access token from the session
  const accessToken = await readAccessToken();
  if (!accessToken) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Get query params for filtering
  const { searchParams } = new URL(request.url);
  const workflow = searchParams.get("workflow");
  const status = searchParams.get("status");
  const vehicle_id = searchParams.get("vehicle_id");
  const document_id = searchParams.get("document_id");
  const correlation_id = searchParams.get("correlation_id");

  // Build the upstream URL
  const params = new URLSearchParams();
  if (workflow) params.set("workflow", workflow);
  if (status) params.set("status", status);
  if (vehicle_id) params.set("vehicle_id", vehicle_id);
  if (document_id) params.set("document_id", document_id);
  if (correlation_id) params.set("correlation_id", correlation_id);

  const upstreamUrl = `${API_BASE_URL}/workflow/events/stream${params.toString() ? `?${params.toString()}` : ""}`;

  try {
    // Fetch the SSE stream from the backend
    const upstreamResponse = await fetch(upstreamUrl, {
      method: "GET",
      headers: {
        Accept: "text/event-stream",
        Authorization: `Bearer ${accessToken}`,
      },
      // Don't cache SSE streams
      cache: "no-store",
    });

    if (!upstreamResponse.ok) {
      if (upstreamResponse.status === 401) {
        return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
      }
      return NextResponse.json(
        { error: "Failed to connect to workflow stream" },
        { status: upstreamResponse.status },
      );
    }

    // Create a TransformStream to pipe the SSE data
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();

    // Pipe the upstream response body to the writable stream
    const reader = upstreamResponse.body?.getReader();
    if (reader) {
      // Pump data from upstream to downstream
      reader.read().then(function pump({ done, value }) {
        if (done) {
          writer.close();
          return;
        }
        writer.write(value).then(() => reader.read().then(pump));
      });
    }

    // Return the readable stream as an SSE response
    return new NextResponse(readable, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (error) {
    console.error("Workflow stream error:", error);
    return NextResponse.json(
      { error: "Failed to establish workflow stream" },
      { status: 500 },
    );
  }
}
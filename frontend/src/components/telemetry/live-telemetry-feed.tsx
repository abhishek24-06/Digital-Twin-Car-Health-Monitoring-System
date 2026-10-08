"use client";

import * as React from "react";
import { Radio } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  useTelemetryStream,
  type TelemetryStreamStatus,
  type UseTelemetryStreamOptions,
} from "@/hooks/use-telemetry-stream";
import { formatTime, formatMetricValue } from "@/lib/format";
import { HEADLINE_METRICS } from "@/lib/metrics";
import { telemetryApi } from "@/services/vehicles";
import type { TelemetryResponse } from "@/types/api";
import { cn } from "@/lib/utils";

const STATUS_VIEWS: Record<
  TelemetryStreamStatus,
  { label: string; dot: string; text: string }
> = {
  idle: { label: "Off", dot: "bg-ink-subtle/50", text: "text-ink-subtle" },
  connecting: { label: "Connecting", dot: "bg-[color:var(--color-attention)]", text: "text-ink-muted" },
  open: { label: "Live", dot: "bg-[color:var(--color-healthy)]", text: "text-ink" },
  reconnecting: {
    label: "Reconnecting",
    dot: "bg-[color:var(--color-attention)]",
    text: "text-ink-muted",
  },
  error: { label: "Offline", dot: "bg-[color:var(--color-critical)]", text: "text-ink-muted" },
};

/** A stream considered stale when no frame has arrived for this long. */
const STALE_AFTER_MS = 10_000;
/** Poll cadence used while the stream is unavailable (fallback). */
const FALLBACK_POLL_MS = 5_000;

function useNow(intervalMs: number): number {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/**
 * Live telemetry feed: subscribes to the vehicle's SSE stream and shows the
 * most recent engine snapshot as it arrives. While the stream is down it falls
 * back to polling the telemetry endpoint, and it flags stale data when no new
 * frame has arrived for a while.
 */
export function LiveTelemetryFeed({
  vehicleId,
  className,
  eventSourceFactory,
}: {
  vehicleId: string;
  className?: string;
  eventSourceFactory?: UseTelemetryStreamOptions["eventSourceFactory"];
}) {
  const { status, samples, lastEventAt, error } = useTelemetryStream(vehicleId, {
    eventSourceFactory,
  });
  const now = useNow(1_000);
  const [fallbackSample, setFallbackSample] = React.useState<TelemetryResponse | null>(null);

  const streamDown = status === "error" || status === "reconnecting";

  React.useEffect(() => {
    if (!streamDown || !vehicleId) return;
    let disposed = false;
    const controller = new AbortController();

    const poll = async () => {
      try {
        const page = await telemetryApi.list(
          vehicleId,
          { pageSize: 1 },
          controller.signal,
        );
        if (disposed) return;
        const newest = page.items[0] ?? null;
        if (newest) setFallbackSample(newest);
      } catch {
        // Transient failure: keep showing the last polled snapshot.
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), FALLBACK_POLL_MS);
    return () => {
      disposed = true;
      clearInterval(timer);
      controller.abort();
    };
  }, [streamDown, vehicleId]);

  const isOpen = status === "open";
  const isStale =
    isOpen && lastEventAt !== null && now - Date.parse(lastEventAt) > STALE_AFTER_MS;
  const latest = isOpen ? (samples[0] ?? null) : null;
  const displayed = latest ?? fallbackSample;

  const view =
    isOpen && isStale
      ? { label: "Stale", dot: "bg-[color:var(--color-attention)]", text: "text-ink-muted" }
      : STATUS_VIEWS[status];

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader>
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <Radio className="size-4 text-ink-subtle" aria-hidden />
              Live telemetry
            </span>
          </CardTitle>
          <CardDescription>
            New samples are pushed the moment the ingestion pipeline stores them.
          </CardDescription>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[0.68rem] font-medium",
            view.text,
          )}
        >
          <span
            className={cn("size-2 rounded-full", view.dot, isOpen && !isStale && "animate-pulse")}
            aria-hidden
          />
          {view.label}
        </span>
      </CardHeader>

      <CardContent>
        {status === "idle" ? (
          <p className="text-[0.8rem] text-ink-subtle">Select a vehicle to begin streaming.</p>
        ) : status === "reconnecting" ? (
          <div className="space-y-3">
            <p className="text-[0.8rem] text-ink-muted">
              The live connection was interrupted — reconnecting automatically.
            </p>
            {displayed ? <FeedSnapshot sample={displayed} fallback /> : null}
          </div>
        ) : status === "error" ? (
          <div className="space-y-3">
            <p className="text-[0.8rem] text-ink-muted">
              {error ?? "The live connection dropped and could not be restored."}
            </p>
            {displayed ? <FeedSnapshot sample={displayed} fallback /> : null}
          </div>
        ) : isStale ? (
          <div className="space-y-3">
            <p className="text-[0.8rem] text-ink-muted">
              No new frames for a while — the pipeline may be idle. Last frame{" "}
              <span className="tabular text-ink">{formatTime(lastEventAt)}</span>.
            </p>
            {displayed ? <FeedSnapshot sample={displayed} /> : null}
          </div>
        ) : displayed ? (
          <FeedSnapshot sample={displayed} lastFrameAt={lastEventAt} liveCount={samples.length} />
        ) : (
          <p className="text-[0.8rem] text-ink-subtle">
            Waiting for the first frame from the stream.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function FeedSnapshot({
  sample,
  lastFrameAt,
  liveCount,
  fallback = false,
}: {
  sample: TelemetryResponse;
  lastFrameAt?: string | null;
  liveCount?: number;
  fallback?: boolean;
}) {
  return (
    <div className="space-y-3">
      {fallback ? (
        <p className="text-[0.68rem] text-ink-subtle">
          Polling fallback · last snapshot{" "}
          <span className="tabular text-ink">{formatTime(sample.timestamp)}</span>
        </p>
      ) : lastFrameAt ? (
        <p className="tabular text-[0.68rem] text-ink-subtle">
          Latest frame {formatTime(lastFrameAt)}
        </p>
      ) : null}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {HEADLINE_METRICS.map((metric) => {
          const value = sample[metric.key as keyof typeof sample] as number | null | undefined;
          return (
            <div key={metric.key}>
              <dt className="text-[0.68rem] text-ink-muted">
                {metric.label}
                <span className="ml-1 text-ink-subtle">{metric.unit}</span>
              </dt>
              <dd className="tabular text-sm font-medium text-ink">
                {formatMetricValue(value, metric.unit)}
              </dd>
            </div>
          );
        })}
      </dl>
      {!fallback && liveCount !== undefined ? (
        <p className="text-[0.68rem] text-ink-subtle">
          {liveCount} live sample{liveCount === 1 ? "" : "s"} buffered
        </p>
      ) : null}
    </div>
  );
}
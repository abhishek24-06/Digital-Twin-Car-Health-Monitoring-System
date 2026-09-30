"use client";

import * as React from "react";
import { Activity } from "lucide-react";
import { metricMeta } from "@/lib/metrics";
import { Sparkline, SERIES_COLORS } from "@/components/health/telemetry-chart";
import { cn } from "@/lib/utils";
import type { MetricStatistics, TelemetryResponse } from "@/types/api";

/**
 * Headline metric card for the dashboard.
 *
 * Shows the latest observed value, the min–max band from the analysis window
 * and a sparkline of the raw samples. Every number here is derived from the
 * backend's telemetry/analysis response — nothing is synthesised client-side.
 */
export function MetricTile({
  metric,
  latest,
  statistics,
  samples,
  className,
}: {
  metric: string;
  latest: TelemetryResponse | null;
  statistics: MetricStatistics | undefined;
  samples: readonly TelemetryResponse[];
  className?: string;
}) {
  const meta = metricMeta(metric);
  const decimals = meta?.decimals ?? 1;
  const unit = meta?.unit ?? "";

  const seriesValues = React.useMemo(
    () =>
      samples
        .map((sample) => sample[metric as keyof TelemetryResponse])
        .filter((value): value is number => typeof value === "number"),
    [samples, metric],
  );

  const current =
    typeof latest?.[metric as keyof TelemetryResponse] === "number"
      ? (latest[metric as keyof TelemetryResponse] as number)
      : (statistics?.last ?? null);

  const band =
    statistics && statistics.minimum !== null && statistics.maximum !== null
      ? `${statistics.minimum.toFixed(decimals)}–${statistics.maximum.toFixed(decimals)}`
      : null;

  const isPercentDomain = meta?.domain?.[0] === 0 && meta.domain?.[1] === 100;

  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-panel)]",
        "transition-colors hover:border-line-strong",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 truncate text-xs font-medium text-ink-subtle">
            <Activity className="size-3 shrink-0" aria-hidden />
            {meta?.label ?? metric}
          </p>
          <p className="tabular mt-2 flex items-baseline gap-1">
            <span className="text-2xl font-semibold tracking-tight text-ink">
              {current === null ? "—" : current.toFixed(decimals)}
            </span>
            {unit ? <span className="text-xs text-ink-subtle">{unit}</span> : null}
          </p>
        </div>

        {seriesValues.length > 1 ? (
          <Sparkline
            values={seriesValues}
            color={SERIES_COLORS[metric] ?? "var(--signal-400)"}
            className="mt-1 shrink-0 opacity-80"
          />
        ) : null}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 text-[0.68rem] text-ink-subtle">
        <span className="tabular">
          {band ? (
            <>
              band <span className="opacity-60">{unit}</span>
            </>
          ) : (
            "no data"
          )}
        </span>
        {isPercentDomain && current !== null ? (
          <span className="tabular inline-flex h-1.5 w-16 overflow-hidden rounded-full bg-surface-3">
            <span
              className="h-full rounded-full"
              style={{
                width: `${Math.max(2, Math.min(100, current))}%`,
                background: SERIES_COLORS[metric] ?? "var(--signal-400)",
              }}
              aria-hidden
            />
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** Compact "no telemetry yet" placeholder used in place of the tiles. */
export function MetricTileSkeleton() {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="h-3 w-24 animate-pulse rounded bg-surface-3" />
      <div className="mt-3 h-7 w-16 animate-pulse rounded bg-surface-3" />
      <div className="mt-4 h-2 w-full animate-pulse rounded bg-surface-3" />
    </div>
  );
}

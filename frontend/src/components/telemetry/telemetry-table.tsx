"use client";

import * as React from "react";
import { metricMeta } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import type { TelemetryResponse } from "@/types/api";

/**
 * Raw telemetry table.
 *
 * Columns come from the backend's `METRIC_UNITS` registry mirrored in
 * `lib/metrics.ts`, and every cell renders the real stored value — missing values
 * show as "—" rather than being interpolated.
 */
export function TelemetryTable({
  samples,
  metrics,
  className,
}: {
  samples: readonly TelemetryResponse[];
  metrics: readonly string[];
  className?: string;
}) {
  if (samples.length === 0) {
    return (
      <p className={cn("px-4 py-8 text-center text-xs text-ink-subtle", className)}>
        No telemetry samples in this range.
      </p>
    );
  }

  return (
    <div className={cn("w-full overflow-x-auto scrollbar-slim", className)}>
      <table className="w-full min-w-[46rem] border-collapse text-left">
        <caption className="sr-only">
          Telemetry samples, newest first. Columns show each metric with its unit.
        </caption>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="px-4 py-2.5 text-[0.68rem] font-medium uppercase tracking-wider text-ink-subtle">
              Time
            </th>
            {metrics.map((key) => {
              const meta = metricMeta(key);
              return (
                <th
                  key={key}
                  scope="col"
                  className="px-3 py-2.5 text-right text-[0.68rem] font-medium uppercase tracking-wider text-ink-subtle"
                >
                  {meta?.shortLabel ?? key}
                  {meta?.unit ? (
                    <span className="ml-1 normal-case tracking-normal opacity-70">
                      {meta.unit}
                    </span>
                  ) : null}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {samples.map((sample) => (
            <tr
              key={sample.id}
              className="border-b border-line/60 transition-colors last:border-0 hover:bg-surface-2"
            >
              <th scope="row" className="whitespace-nowrap px-4 py-2 text-xs font-normal text-ink-muted">
                <time dateTime={sample.timestamp}>{formatStamp(sample.timestamp)}</time>
              </th>
              {metrics.map((key) => {
                const value = sample[key as keyof TelemetryResponse];
                const meta = metricMeta(key);
                return (
                  <td
                    key={key}
                    className={cn(
                      "tabular whitespace-nowrap px-3 py-2 text-right text-xs",
                      typeof value === "number" ? "text-ink" : "text-ink-subtle",
                    )}
                  >
                    {typeof value === "number"
                      ? value.toFixed(meta?.decimals ?? 1)
                      : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function formatStamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

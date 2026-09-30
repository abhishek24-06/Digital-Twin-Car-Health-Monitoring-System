"use client";

import * as React from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { metricMeta } from "@/lib/metrics";
import type { TelemetryResponse } from "@/types/api";
import { cn } from "@/lib/utils";

/**
 * Multi-metric telemetry chart.
 *
 * Recharts is rendered client-side only (see the `use client` boundary) and is
 * given an explicit `min-h` so the responsive container never collapses. Values
 * are ordered oldest → newest for the x-axis; the API returns newest first.
 */

export interface SeriesSpec {
  key: string;
  color: string;
  /** Override the palette when a metric appears twice. */
  axis?: "left" | "right";
}

export const SERIES_COLORS: Record<string, string> = {
  coolant_temperature: "var(--color-attention)",
  oil_temperature: "var(--color-critical)",
  battery_voltage: "var(--color-signal-400)",
  engine_load: "var(--color-info)",
  rpm: "var(--color-signal-300)",
  fuel_level: "var(--color-healthy)",
  speed: "var(--color-signal-500)",
  intake_air_temperature: "var(--color-unknown)",
  throttle_position: "var(--color-info)",
  engine_runtime: "var(--color-ink-subtle)",
  odometer: "var(--color-ink-subtle)",
};

interface ChartRow extends Record<string, string | number | null> {
  ts: number;
}

function formatClock(ts: number, spanMinutes: number): string {
  const date = new Date(ts);
  if (spanMinutes > 720) {
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function TelemetryChart({
  samples,
  metrics,
  className,
  height = 280,
}: {
  samples: TelemetryResponse[];
  metrics: readonly string[];
  className?: string;
  height?: number;
}) {
  const rows = React.useMemo<ChartRow[]>(() => {
    return [...samples]
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
      .map((sample) => {
        const row: ChartRow = { ts: new Date(sample.timestamp).getTime() };
        for (const key of metrics) {
          const value = sample[key as keyof TelemetryResponse];
          row[key] = typeof value === "number" ? value : null;
        }
        return row;
      });
  }, [samples, metrics]);

  const spanMinutes =
    rows.length > 1 ? (rows[rows.length - 1].ts - rows[0].ts) / 60_000 : 60;

  const activeMetrics = metrics.filter((key) =>
    rows.some((row) => typeof row[key] === "number"),
  );

  if (rows.length === 0 || activeMetrics.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center rounded-lg border border-dashed border-line px-6 py-12 text-center",
          className,
        )}
        style={{ minHeight: height }}
      >
        <p className="max-w-sm text-xs leading-relaxed text-ink-subtle">
          No samples for the selected metrics in this time range. Choose a wider
          range, or wait for the telemetry pipeline to deliver more data.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("w-full", className)} style={{ minHeight: height }}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="var(--line)" vertical={false} />
          <XAxis
            dataKey="ts"
            type="number"
            domain={["dataMin", "dataMax"]}
            scale="time"
            tickFormatter={(value: number) => formatClock(value, spanMinutes)}
            stroke="var(--ink-subtle)"
            tick={{ fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "var(--line)" }}
            minTickGap={32}
          />
          <YAxis
            yAxisId="left"
            stroke="var(--ink-subtle)"
            tick={{ fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={44}
            domain={["auto", "auto"]}
            tickFormatter={(value: number) =>
              Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
            }
          />
          {activeMetrics.length > 1 ? (
            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="var(--ink-subtle)"
              tick={{ fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={40}
              tickFormatter={(value: number) => String(value)}
            />
          ) : null}

          <RechartsTooltip
            content={
              <TelemetryTooltip metrics={activeMetrics} />
            }
            labelFormatter={(value) => new Date(Number(value)).toLocaleString()}
          />
          <Legend
            verticalAlign="top"
            height={28}
            iconType="plainline"
            wrapperStyle={{ fontSize: 12 }}
          />

          {activeMetrics.map((key, index) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              name={`${metricMeta(key)?.label ?? key}${
                metricMeta(key)?.unit ? ` (${metricMeta(key)?.unit})` : ""
              }`}
              stroke={SERIES_COLORS[key] ?? "var(--signal-400)"}
              strokeWidth={1.75}
              dot={false}
              activeDot={{ r: 3 }}
              connectNulls
              isAnimationActive={false}
              // Alternate axes so overlapping ranges stay readable.
              yAxisId={index % 2 === 0 ? "left" : "right"}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function TelemetryTooltip({
  active,
  label,
  payload,
  metrics,
}: {
  active?: boolean;
  label?: React.ReactNode;
  payload?: ReadonlyArray<{ dataKey?: string | number; value?: number | string }>;
  metrics: readonly string[];
}) {
  if (!active || !payload || payload.length === 0) return null;

  const entries = payload
    .filter((entry) => metrics.includes(String(entry.dataKey)))
    .map((entry) => {
      const key = String(entry.dataKey);
      const meta = metricMeta(key);
      const value = typeof entry.value === "number" ? entry.value : Number(entry.value);
      return {
        key,
        label: meta?.label ?? key,
        unit: meta?.unit ?? "",
        value: Number.isFinite(value)
          ? value.toFixed(meta?.decimals ?? 1)
          : "—",
        color: SERIES_COLORS[key] ?? "var(--signal-400)",
      };
    });

  if (entries.length === 0) return null;

  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 shadow-[var(--shadow-pop)]">
      <p className="mb-1.5 text-[0.7rem] text-ink-subtle">{label}</p>
      <ul className="space-y-1">
        {entries.map((entry) => (
          <li key={entry.key} className="flex items-center gap-2 text-xs">
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ background: entry.color }}
              aria-hidden
            />
            <span className="text-ink-muted">{entry.label}</span>
            <span className="tabular ml-auto font-medium text-ink">
              {entry.value}
              {entry.unit ? <span className="text-ink-subtle"> {entry.unit}</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Tiny inline sparkline for dashboard tiles. Pure SVG so it stays cheap for the
 * six headline metrics.
 */
export function Sparkline({
  values,
  color = "var(--signal-400)",
  width = 96,
  height = 28,
  className,
}: {
  values: readonly number[];
  color?: string;
  width?: number;
  height?: number;
  className?: string;
}) {
  const points = React.useMemo(() => {
    const clean = values.filter((value) => Number.isFinite(value));
    if (clean.length < 2) return "";
    const min = Math.min(...clean);
    const max = Math.max(...clean);
    const span = max - min || 1;
    return clean
      .map((value, index) => {
        const x = (index / (clean.length - 1)) * (width - 2) + 1;
        const y = height - 2 - ((value - min) / span) * (height - 4);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [values, width, height]);

  if (!points) return null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      aria-hidden
      focusable="false"
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

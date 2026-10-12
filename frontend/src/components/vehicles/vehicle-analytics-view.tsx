"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { BarChart3, GitCommitHorizontal, TimerReset } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SelectMenu, type SelectOption } from "@/components/ui/select-menu";
import { EmptyState, ErrorState } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { useHistoricalAnalytics } from "@/hooks/use-vehicle-data";
import {
  formatDateTime,
  formatDuration,
  formatNumber,
  formatTime,
} from "@/lib/format";
import { metricLabel, metricUnit } from "@/lib/metrics";
import type {
  HistoricalAnalyticsResponse,
  HistoricalRangePreset,
} from "@/types/api";

const RANGE_OPTIONS: ReadonlyArray<SelectOption<HistoricalRangePreset>> = [
  { value: "1h", label: "Last hour", description: "Rolling 1-hour window" },
  { value: "24h", label: "Last 24 hours", description: "Rolling day of telemetry" },
  { value: "7d", label: "Last 7 days", description: "Rolling week" },
  { value: "30d", label: "Last 30 days", description: "Rolling month" },
  { value: "90d", label: "Last 90 days", description: "Rolling quarter" },
  { value: "custom", label: "Custom range", description: "Explicit UTC start and end" },
];

const TREND_TONE: Record<string, "healthy" | "attention" | "neutral"> = {
  stable: "neutral",
  increasing: "attention",
  decreasing: "attention",
  insufficient_data: "neutral",
};

function toLocalInputValue(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

/**
 * Historical Analytics: read-only aggregates over a validated historical
 * window of persisted telemetry — per-metric statistics, deterministic trends,
 * run-boundary segments, time-bucketed sample counts and gap disclosure. This
 * is the honest counterpart to the live view: historical is what the pipeline
 * *persisted*, live is the current session only.
 */
export function VehicleAnalyticsView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  const [range, setRange] = React.useState<HistoricalRangePreset>("24h");
  const [timezone, setTimezone] = React.useState("UTC");
  const [customStart, setCustomStart] = React.useState(() =>
    toLocalInputValue(new Date(Date.now() - 24 * 3600_000)),
  );
  const [customEnd, setCustomEnd] = React.useState(() =>
    toLocalInputValue(new Date()),
  );

  const spec = React.useMemo(() => {
    if (range !== "custom") {
      return { range, timezone, startTime: undefined, endTime: undefined };
    }
    const start = new Date(customStart);
    const end = new Date(customEnd);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;
    return {
      range,
      timezone,
      startTime: start.toISOString(),
      endTime: end.toISOString(),
    };
  }, [range, timezone, customStart, customEnd]);

  const analytics = useHistoricalAnalytics(spec ? vehicleId : null, spec ?? null);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-signal-400">
              <BarChart3 className="size-4" aria-hidden />
            </span>
            <div>
              <CardTitle>Historical analytics</CardTitle>
              <CardDescription>
                Aggregates over persisted telemetry for a validated window. All
                timestamps are UTC; a custom range must be timezone-aware and
                forward (reversed ranges are rejected).
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-ink-muted">Range</span>
              <SelectMenu
                value={range}
                options={RANGE_OPTIONS}
                onChange={setRange}
                label="Analytics range"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-ink-muted">Timezone</span>
              <Input
                type="text"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                aria-label="Analytics timezone (IANA name)"
                className="font-mono text-xs"
              />
            </label>
          </div>

          {range === "custom" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-ink-muted">
                  Start (local time)
                </span>
                <Input
                  type="datetime-local"
                  value={customStart}
                  onChange={(event) => setCustomStart(event.target.value)}
                  aria-label="Custom range start"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-ink-muted">
                  End (local time)
                </span>
                <Input
                  type="datetime-local"
                  value={customEnd}
                  onChange={(event) => setCustomEnd(event.target.value)}
                  aria-label="Custom range end"
                />
              </label>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {analytics.isPending ? (
        <div className="grid gap-4">
          <Skeleton className="h-28 w-full rounded-xl" />
          <Skeleton className="h-48 w-full rounded-xl" />
        </div>
      ) : analytics.isError ? (
        <ErrorState error={analytics.error} onRetry={() => analytics.refetch()} />
      ) : analytics.data ? (
        <AnalyticsBody data={analytics.data} />
      ) : (
        <EmptyState
          icon={<BarChart3 className="size-5" aria-hidden />}
          title="Invalid range"
          description="Enter a timezone-aware, forward custom range to see historical analytics."
        />
      )}
    </div>
  );
}

function AnalyticsBody({ data }: { data: HistoricalAnalyticsResponse }) {
  const empty = data.total_samples === 0;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Window summary</CardTitle>
            <CardDescription>
              {formatDateTime(data.window_start)} → {formatDateTime(data.window_end)} (
              {formatDuration(data.duration_seconds)}) in {data.timezone}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {empty ? (
            <p className="text-xs text-ink-subtle">
              No telemetry was persisted inside this window. The live session may
              be collecting, or this vehicle has not produced data in this period.
            </p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs sm:grid-cols-4">
              <HistFact
                label="Persisted samples"
                value={formatNumber(data.total_samples)}
              />
              <HistFact
                label="Earliest sample"
                value={
                  data.earliest_sample_at
                    ? formatDateTime(data.earliest_sample_at)
                    : "—"
                }
              />
              <HistFact
                label="Latest sample"
                value={
                  data.latest_sample_at ? formatDateTime(data.latest_sample_at) : "—"
                }
              />
              <HistFact
                label="Health snapshots"
                value={`${formatNumber(data.snapshot_count)}${
                  data.snapshots_present ? "" : " (none)"
                }`}
              />
              <HistFact
                label="Run segments"
                value={formatNumber(data.run_segments.length)}
              />
              <HistFact
                label="Gaps beyond tolerance"
                value={formatNumber(data.gaps.gap_count)}
              />
              <HistFact
                label="Largest gap"
                value={
                  data.gaps.max_gap_seconds === null
                    ? "—"
                    : formatDuration(data.gaps.max_gap_seconds)
                }
              />
              <HistFact
                label="Expected interval"
                value={formatDuration(data.gaps.expected_interval_seconds)}
              />
            </dl>
          )}
        </CardContent>
      </Card>

      <BucketChart data={data} />

      <div className="grid gap-4 lg:grid-cols-2">
        <MetricTable data={data} />
        <RunSegments data={data} />
      </div>
    </div>
  );
}

function BucketChart({ data }: { data: HistoricalAnalyticsResponse }) {
  if (data.buckets.length === 0) return null;
  const max = Math.max(...data.buckets.map((bucket) => bucket.sample_count), 1);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Samples over time</CardTitle>
          <CardDescription>
            Counts per {bucketLabel(data)} bucket — reflects persisted rows, not
            live streaming.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div
          className="flex h-28 items-end gap-px"
          role="img"
          aria-label="Time-bucketed sample counts"
        >
          {data.buckets.map((bucket) => (
            <div
              key={bucket.bucket_start}
              className="min-w-px flex-1 rounded-sm bg-[color:var(--color-signal-500)]/70"
              style={{
                height: `${Math.max(2, (bucket.sample_count / max) * 100)}%`,
              }}
              title={`${formatTime(bucket.bucket_start)}: ${bucket.sample_count} samples`}
            />
          ))}
        </div>
        <div className="mt-2 flex justify-between text-[0.65rem] text-ink-subtle">
          <span>{formatTime(data.buckets[0]?.bucket_start)}</span>
          <span>{formatTime(data.buckets.at(-1)?.bucket_end)}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function bucketLabel(data: HistoricalAnalyticsResponse): string {
  if (data.duration_seconds <= 2 * 3600) return "10 minutes";
  if (data.duration_seconds <= 48 * 3600) return "hour";
  return "day";
}

function MetricTable({ data }: { data: HistoricalAnalyticsResponse }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Metric aggregates</CardTitle>
          <CardDescription>
            Per-metric statistics over the window ({data.total_samples} persisted
            samples)
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-xs">
          <thead>
            <tr className="border-b border-line text-[0.65rem] uppercase tracking-wider text-ink-subtle">
              <th className="py-2 pr-3 font-medium">Metric</th>
              <th className="py-2 pr-3 font-medium">n</th>
              <th className="py-2 pr-3 text-right font-medium">min</th>
              <th className="py-2 pr-3 text-right font-medium">mean</th>
              <th className="py-2 pr-3 text-right font-medium">median</th>
              <th className="py-2 pr-3 text-right font-medium">max</th>
              <th className="py-2 pr-3 text-right font-medium">Δ last−first</th>
              <th className="py-2 font-medium">Trend</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data.metrics.map((metric) => {
              const trend = data.trends.find((t) => t.metric === metric.metric);
              return (
                <tr key={metric.metric}>
                  <td className="py-2 pr-3 font-medium text-ink">
                    {metricLabel(metric.metric)}
                    <span className="ml-1 text-[0.65rem] text-ink-subtle">
                      {metricUnit(metric.metric)}
                    </span>
                  </td>
                  <td className="py-2 pr-3 tabular text-ink-subtle">
                    {formatNumber(metric.valid_samples)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular">
                    {num(metric.min_value)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular">
                    {num(metric.mean_value)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular">
                    {num(metric.median_value)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular">
                    {num(metric.max_value)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular">
                    {num(metric.delta_value)}
                  </td>
                  <td className="py-2">
                    {trend ? (
                      <Badge tone={TREND_TONE[trend.direction] ?? "neutral"} size="sm">
                        {trend.direction}
                        {trend.strength ? ` · ${trend.strength}` : ""}
                      </Badge>
                    ) : (
                      <span className="text-ink-subtle">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function RunSegments({ data }: { data: HistoricalAnalyticsResponse }) {
  if (data.run_segments.length === 0) {
    return (
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Run boundaries</CardTitle>
            <CardDescription>Simulator-run segments in this window</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <p className="flex items-center gap-1.5 text-xs text-ink-subtle">
            <GitCommitHorizontal className="size-3.5" aria-hidden />
            No persisted telemetry in this window, so no run segments exist.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Run boundaries</CardTitle>
          <CardDescription>
            Segments recovered from the persisted run id on each sample
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <ul className="space-y-1.5">
          {data.run_segments.map((segment) => (
            <li
              key={segment.run_id ?? "legacy"}
              className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs"
            >
              {segment.is_legacy ? (
                <span className="font-mono text-[0.65rem] text-ink-muted">
                  legacy (no run id)
                </span>
              ) : (
                <span className="max-w-40 truncate font-mono text-[0.65rem] text-ink">
                  {segment.run_id}
                </span>
              )}
              <span className="tabular text-ink-subtle">
                {formatNumber(segment.samples)} samples
              </span>
              <span className="ml-auto tabular text-ink-subtle">
                {segment.first_timestamp ? formatTime(segment.first_timestamp) : "—"}
                {" → "}
                {segment.last_timestamp ? formatTime(segment.last_timestamp) : "—"}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 flex items-center gap-1.5 text-[0.68rem] text-ink-subtle">
          <TimerReset className="size-3" aria-hidden />
          Segments are evidence of when a simulator run produced data — cleanly
          separated from the live view of the current session.
        </p>
      </CardContent>
    </Card>
  );
}

function HistFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.62rem] uppercase tracking-wider text-ink-subtle">
        {label}
      </dt>
      <dd className="tabular mt-0.5 text-ink">{value}</dd>
    </div>
  );
}

function num(value: number | null): string {
  return value === null ? "—" : formatNumber(value, 1);
}
"use client";

import * as React from "react";
import { Check, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/select-menu";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState, ErrorState } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { TelemetryChart } from "@/components/health/telemetry-chart";
import { TelemetryTable } from "@/components/telemetry/telemetry-table";
import { useTelemetryWindow, type TelemetryRangeSpec } from "@/hooks/use-vehicle-data";
import { cn } from "@/lib/utils";
import { HEADLINE_METRICS, TELEMETRY_METRICS, TIME_RANGES } from "@/lib/metrics";

const PAGE_SIZE = 100;

/**
 * Telemetry explorer: time range + metric selection + chart + paginated table.
 *
 * Time windows map directly onto the backend's `start_time` / `end_time`
 * filters; there is no client-side resampling or interpolation.
 */
export function TelemetryExplorer({
  vehicleId,
  className,
  initialRangeKey = "1h",
  initialMetrics = HEADLINE_METRICS.map((metric) => metric.key),
}: {
  vehicleId: string;
  className?: string;
  initialRangeKey?: string;
  initialMetrics?: readonly string[];
}) {
  const [rangeKey, setRangeKey] = React.useState(initialRangeKey);
  const [selected, setSelected] = React.useState<string[]>([...initialMetrics]);
  const [page, setPage] = React.useState(1);

  // Anchor only drives the displayed window label; the query itself always
  // requests a trailing window so pagination never shifts the data underfoot.
  const [windowAnchor, setWindowAnchor] = React.useState(() => Date.now());

  const range = React.useMemo<TelemetryRangeSpec>(() => {
    const option = TIME_RANGES.find((item) => item.key === rangeKey) ?? TIME_RANGES[2];
    return { key: option.key, minutes: option.minutes };
  }, [rangeKey]);

  const windowStart = windowAnchor - range.minutes * 60_000;

  const { data, isPending, isError, error, isFetching, refetch } =
    useTelemetryWindow(vehicleId, range, { page, pageSize: PAGE_SIZE });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const toggleMetric = (key: string) => {
    setSelected((current) => {
      if (current.includes(key)) {
        return current.length === 1 ? current : current.filter((item) => item !== key);
      }
      return [...current, key];
    });
  };

  const changeRange = (key: string) => {
    setRangeKey(key);
    setPage(1);
    setWindowAnchor(Date.now());
  };

  return (
    <div className={cn("space-y-4", className)}>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Telemetry</CardTitle>
            <CardDescription>
              Raw samples from the ingestion pipeline · newest first
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {isFetching && !isPending ? (
              <span className="inline-flex items-center gap-1.5 text-[0.68rem] text-ink-subtle">
                <RefreshCw className="size-3 animate-spin" aria-hidden />
                updating
              </span>
            ) : null}
            <Button
              size="iconSm"
              variant="outline"
              onClick={() => refetch()}
              aria-label="Refresh telemetry"
            >
              <RefreshCw aria-hidden />
            </Button>
          </div>
        </CardHeader>

        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-5">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <SegmentedControl
              ariaLabel="Time range"
              value={rangeKey}
              options={TIME_RANGES.map((item) => ({
                value: item.key,
                label: item.label,
              }))}
              onChange={changeRange}
            />
            <p className="tabular text-[0.68rem] text-ink-subtle">
              {formatWindow(windowStart)} → {formatWindow(windowAnchor)}
            </p>
          </div>

          <fieldset className="flex flex-wrap items-center gap-1.5">
            <legend className="sr-only">Visible metrics</legend>
            {TELEMETRY_METRICS.map((meta) => {
              const active = selected.includes(meta.key);
              return (
                <button
                  key={meta.key}
                  type="button"
                  onClick={() => toggleMetric(meta.key)}
                  aria-pressed={active}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[0.68rem] transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
                    active
                      ? "border-signal-500/60 bg-signal-500/10 text-ink"
                      : "border-line bg-surface-2 text-ink-subtle hover:text-ink",
                  )}
                >
                  <span
                    className={cn(
                      "grid size-3 place-items-center rounded-[3px] border",
                      active ? "border-signal-400 bg-signal-500/30" : "border-line",
                    )}
                    aria-hidden
                  >
                    {active ? <Check className="size-2.5 text-signal-200" /> : null}
                  </span>
                  {meta.shortLabel}
                  <span className="text-ink-subtle">{meta.unit}</span>
                </button>
              );
            })}
          </fieldset>
        </div>

        <CardContent className="px-2 py-4 sm:px-3">
          {isPending ? (
            <div className="space-y-3 px-2">
              <Skeleton className="h-[280px] w-full rounded-lg" />
              <Skeleton className="h-3 w-40" />
            </div>
          ) : isError ? (
            <ErrorState
              error={error}
              onRetry={() => refetch()}
              className="mx-2"
            />
          ) : (
            <TelemetryChart samples={items} metrics={selected} />
          )}
        </CardContent>

        {total > 0 ? (
          <CardFooter className="justify-between gap-3 border-t border-line px-4 sm:px-5">
            <p className="tabular text-xs text-ink-subtle">
              {total.toLocaleString()} sample{total === 1 ? "" : "s"} in range
            </p>
            <p className="text-[0.68rem] text-ink-subtle">
              Showing page {page} · {PAGE_SIZE} per page
            </p>
          </CardFooter>
        ) : null}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Samples</CardTitle>
          <CardDescription>
            Every value is stored telemetry — nothing here is generated in the browser.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {isPending ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-8 w-full" />
              ))}
            </div>
          ) : isError ? (
            <ErrorState error={error} onRetry={() => refetch()} className="m-4" />
          ) : items.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<RefreshCw className="size-5" aria-hidden />}
                title="No telemetry in this window"
                description={
                  <>
                    The vehicle has no stored samples between{" "}
                    <span className="text-ink-muted">{formatWindow(windowStart)}</span>{" "}
                    and{" "}
                    <span className="text-ink-muted">{formatWindow(windowAnchor)}</span>.
                    Widen the range, or check that the ingestion pipeline is publishing
                    for this VIN.
                  </>
                }
                action={
                  <Button size="sm" variant="outline" onClick={() => changeRange("24h")}>
                    Widen to 24 hours
                  </Button>
                }
              />
            </div>
          ) : (
            <>
              <TelemetryTable samples={items} metrics={selected} />
              <Pagination
                page={data?.page ?? page}
                pageSize={data?.page_size ?? PAGE_SIZE}
                total={total}
                onPageChange={setPage}
                label="Telemetry samples"
              />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function formatWindow(value: string | number): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

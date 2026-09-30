"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowRight,
  Bot,
  TrendingDown,
  TrendingUp,
  Minus,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthSummaryPanel } from "@/components/health/health-summary-panel";
import { FindingsList } from "@/components/health/findings-list";
import { MetricTile, MetricTileSkeleton } from "@/components/health/metric-tile";
import { useAgentDashboard, useHealthContext, useTelemetryWindow } from "@/hooks/use-vehicle-data";
import { useAnalyzeHealth } from "@/hooks/use-mutations";
import { HEADLINE_METRICS, metricLabel } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import type { TrendInsight } from "@/types/api";

const OVERVIEW_MINUTES = 60;

/** Vehicle overview: score, trends, findings, latest values, AI snapshot. */
export function VehicleOverview() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  const range = React.useMemo(
    () => ({ key: "1h", minutes: OVERVIEW_MINUTES }),
    [],
  );

  const health = useHealthContext(vehicleId);
  const telemetry = useTelemetryWindow(vehicleId, range, { pageSize: 100 });
  const agent = useAgentDashboard(vehicleId);
  const analyze = useAnalyzeHealth(vehicleId);

  const latest = telemetry.data?.items?.[0] ?? null;
  const stats = health.data?.statistics;

  return (
    <div className="space-y-4">
      <HealthSummaryPanel
        context={health.data ?? null}
        isAnalyzing={analyze.isPending}
        analyzeError={analyze.isError ? analyze.error : null}
        onAnalyze={(minutes) => analyze.mutate(minutes ?? OVERVIEW_MINUTES)}
      />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Latest values</CardTitle>
            <CardDescription>Newest stored sample across the headline metrics</CardDescription>
          </div>
          <Button asChild variant="ghost" size="sm">
            <Link href={`/vehicles/${vehicleId}/telemetry`}>
              Telemetry
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          {telemetry.isPending ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {HEADLINE_METRICS.slice(0, 6).map((metric) => (
                <MetricTileSkeleton key={metric.key} />
              ))}
            </div>
          ) : telemetry.isError ? (
            <ErrorState error={telemetry.error} compact onRetry={() => telemetry.refetch()} />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {HEADLINE_METRICS.map((metric) => (
                <MetricTile
                  key={metric.key}
                  metric={metric.key}
                  latest={latest}
                  statistics={stats?.[metric.key]}
                  samples={telemetry.data?.items ?? []}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Findings</CardTitle>
              <CardDescription>Rules that fired in the latest window</CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href={`/vehicles/${vehicleId}/health`}>
                Details
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {health.isPending ? (
              <Skeleton className="h-32 w-full" />
            ) : health.isError ? (
              <ErrorState error={health.error} compact onRetry={() => health.refetch()} />
            ) : (
              <FindingsList findings={health.data?.findings ?? []} />
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Trends</CardTitle>
                <CardDescription>Slope of each metric across the analysis window</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              {health.isPending ? (
                <Skeleton className="h-24 w-full" />
              ) : (health.data?.trends.length ?? 0) === 0 ? (
                <p className="text-xs text-ink-subtle">
                  Not enough samples to establish a trend in this window.
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {health.data?.trends.map((trend) => (
                    <TrendRow key={trend.metric} trend={trend} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>AI diagnosis</CardTitle>
                <CardDescription>Latest interpretation, kept separate from measurements</CardDescription>
              </div>
              <Button asChild variant="ghost" size="sm">
                <Link href={`/vehicles/${vehicleId}/diagnosis`}>
                  Open
                  <ArrowRight aria-hidden />
                </Link>
              </Button>
            </CardHeader>
            <CardContent>
              {agent.isPending ? (
                <Skeleton className="h-16 w-full" />
              ) : agent.isError ? (
                <ErrorState error={agent.error} compact onRetry={() => agent.refetch()} />
              ) : agent.data?.latest_diagnosis ? (
                <p className="text-sm leading-relaxed text-ink">
                  {agent.data.latest_diagnosis.diagnosis.summary}
                </p>
              ) : (
                <EmptyState
                  icon={<Bot className="size-5" aria-hidden />}
                  title="No diagnosis yet"
                  description="Ask the agent a question to generate a grounded interpretation of the current health context."
                  className="border-0 px-0"
                />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function TrendRow({ trend }: { trend: TrendInsight }) {
  const direction = trend.direction;
  const Icon =
    direction === "increasing"
      ? TrendingUp
      : direction === "decreasing"
        ? TrendingDown
        : Minus;
  const color =
    direction === "increasing"
      ? "text-[color:var(--color-attention)]"
      : direction === "decreasing"
        ? "text-[color:var(--color-info)]"
        : "text-ink-subtle";

  return (
    <li className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs">
      <Icon className={cn("size-3.5 shrink-0", color)} aria-hidden />
      <span className="text-ink-muted">{metricLabel(trend.metric)}</span>
      <span className="ml-auto text-[0.65rem] uppercase tracking-wider text-ink-subtle">
        {direction.replace("_", " ")}
        {trend.strength ? ` · ${trend.strength}` : ""}
      </span>
      {trend.normalized_slope !== null ? (
        <span className="tabular w-16 text-right text-[0.65rem] text-ink-subtle">
          {trend.normalized_slope >= 0 ? "+" : ""}
          {trend.normalized_slope.toFixed(3)}
        </span>
      ) : null}
    </li>
  );
}

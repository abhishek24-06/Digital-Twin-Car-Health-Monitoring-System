"use client";

import * as React from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  Bot,
  Car,
  ClipboardList,
  Gauge,
  LineChart as LineChartIcon,
  PlusCircle,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/page-header";
import { HealthScoreRing, HealthStatusBadge } from "@/components/health/health-visuals";
import { MetricTile, MetricTileSkeleton } from "@/components/health/metric-tile";
import { FindingsList } from "@/components/health/findings-list";
import { useActiveVehicleId } from "@/hooks/use-active-vehicle";
import {
  useAgentDashboard,
  useHealthContext,
  useTelemetryWindow,
} from "@/hooks/use-vehicle-data";
import { useVehicles } from "@/hooks/use-vehicle-data";
import { useAnalyzeHealth } from "@/hooks/use-mutations";
import { HEADLINE_METRICS } from "@/lib/metrics";
import { cn } from "@/lib/utils";

const DASHBOARD_RANGE_MINUTES = 60;

/**
 * Dashboard: the current state of the active vehicle at a glance.
 *
 * Everything is read from the live API. When no vehicle exists the page becomes
 * a single clear call to action instead of a wall of empty panels.
 */
export function DashboardView() {
  const { vehicleId, isLoading, isError, error, hasVehicles } = useActiveVehicleId();
  const { data: vehicles } = useVehicles();

  const vehicle = React.useMemo(
    () => vehicles?.find((item) => item.id === vehicleId) ?? null,
    [vehicles, vehicleId],
  );

  const range = React.useMemo(
    () => ({ key: "1h", minutes: DASHBOARD_RANGE_MINUTES }),
    [],
  );

  const health = useHealthContext(vehicleId);
  const telemetry = useTelemetryWindow(vehicleId, range, { pageSize: 100 });
  const agent = useAgentDashboard(vehicleId);
  const analyze = useAnalyzeHealth(vehicleId ?? "");

  const stats = health.data?.statistics;
  const findings = health.data?.findings ?? [];
  const criticalFindings = findings.filter(
    (finding) => finding.severity === "critical",
  );
  const attentionFindings = findings.filter(
    (finding) => finding.severity === "warning",
  );

  if (isError) {
    return (
      <div className="space-y-5">
        <PageHeader title="Dashboard" />
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  if (isLoading) {
    return <DashboardSkeleton />;
  }

  if (!hasVehicles || !vehicleId || !vehicle) {
    return (
      <div className="space-y-5">
        <PageHeader
          title="Dashboard"
          description="Register a vehicle to start monitoring its health."
        />
        <EmptyState
          icon={<Car className="size-5" aria-hidden />}
          title="No vehicles yet"
          description="Add your car with its VIN. Once telemetry arrives, the health engine scores it automatically and the AI agent can explain what it finds."
          action={
            <Button asChild size="sm">
              <Link href="/vehicles">
                <PlusCircle aria-hidden />
                Add a vehicle
              </Link>
            </Button>
          }
        />
      </div>
    );
  }

  const latest = telemetry.data?.items?.[0] ?? null;

  return (
    <div className="space-y-5">
      <PageHeader
        title={`${vehicle.make} ${vehicle.model}`}
        description={
          <>
            {vehicle.year} · VIN{" "}
            <span className="font-mono text-ink-muted">{vehicle.vin}</span>
            {vehicle.engine_type ? ` · ${vehicle.engine_type}` : ""}
          </>
        }
        actions={
          <>
            <Button asChild variant="outline" size="sm">
              <Link href={`/vehicles/${vehicle.id}/telemetry`}>
                <LineChartIcon aria-hidden />
                Telemetry
              </Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href={`/vehicles/${vehicle.id}/diagnosis`}>
                <Sparkles aria-hidden />
                Ask AI
              </Link>
            </Button>
            <Button
              size="sm"
              loading={analyze.isPending}
              onClick={() => analyze.mutate(DASHBOARD_RANGE_MINUTES)}
            >
              <Activity aria-hidden />
              Analyze health
            </Button>
          </>
        }
      />

      {analyze.isError ? (
        <ErrorState error={analyze.error} compact onRetry={() => analyze.mutate(60)} />
      ) : null}

      {criticalFindings.length > 0 ? (
        <InlineAlert tone="critical" title="Critical rule violation detected">
          {criticalFindings.length} rule
          {criticalFindings.length === 1 ? "" : "s"} fired at critical severity in the
          latest analysis window. Open Health for the observed values and thresholds.
        </InlineAlert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Health score</CardTitle>
            <CardDescription>
              {health.data
                ? `Generated ${new Date(health.data.generated_at).toLocaleString()}`
                : "No analysis yet"}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-4">
            {health.isPending ? (
              <Skeleton className="size-[168px] rounded-full" />
            ) : health.isError ? (
              <ErrorState error={health.error} compact onRetry={() => health.refetch()} />
            ) : health.data ? (
              <>
                <HealthScoreRing
                  score={health.data.health_score}
                  status={health.data.health_status}
                />
                <HealthStatusBadge status={health.data.health_status} size="lg" />
                <dl className="grid w-full grid-cols-2 gap-3 border-t border-line pt-3 text-xs">
                  <div>
                    <dt className="text-[0.65rem] uppercase tracking-wider text-ink-subtle">
                      Samples
                    </dt>
                    <dd className="tabular mt-0.5 text-ink">
                      {health.data.data_quality.sample_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.65rem] uppercase tracking-wider text-ink-subtle">
                      Findings
                    </dt>
                    <dd className="tabular mt-0.5 text-ink">{findings.length}</dd>
                  </div>
                  <div>
                    <dt className="text-[0.65rem] uppercase tracking-wider text-ink-subtle">
                      Critical
                    </dt>
                    <dd
                      className={cn(
                        "tabular mt-0.5",
                        criticalFindings.length > 0
                          ? "text-[color:var(--color-critical)]"
                          : "text-ink",
                      )}
                    >
                      {criticalFindings.length}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.65rem] uppercase tracking-wider text-ink-subtle">
                      Attention
                    </dt>
                    <dd
                      className={cn(
                        "tabular mt-0.5",
                        attentionFindings.length > 0
                          ? "text-[color:var(--color-attention)]"
                          : "text-ink",
                      )}
                    >
                      {attentionFindings.length}
                    </dd>
                  </div>
                </dl>
              </>
            ) : (
              <EmptyState
                title="No analysis yet"
                description="Run the deterministic health analysis to score this vehicle from its recent telemetry."
                action={
                  <Button
                    size="sm"
                    loading={analyze.isPending}
                    onClick={() => analyze.mutate(DASHBOARD_RANGE_MINUTES)}
                  >
                    <Gauge aria-hidden />
                    Run analysis
                  </Button>
                }
                className="border-0 px-0"
              />
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>Latest telemetry</CardTitle>
              <CardDescription>Headline metrics from the last hour</CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href={`/vehicles/${vehicle.id}/telemetry`}>
                View all
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
              <ErrorState
                error={telemetry.error}
                compact
                onRetry={() => telemetry.refetch()}
              />
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
            {telemetry.data && telemetry.data.total === 0 ? (
              <p className="mt-3 text-xs text-ink-subtle">
                No samples arrived in the last hour. Open Telemetry to widen the range
                or to inspect what has been stored.
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Rule findings</CardTitle>
              <CardDescription>
                Deterministic thresholds from the latest analysis window
              </CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href={`/vehicles/${vehicle.id}/health`}>
                Health
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {health.isPending ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} className="h-14 w-full" />
                ))}
              </div>
            ) : findings.length === 0 ? (
              <p className="text-xs leading-relaxed text-ink-subtle">
                No rule fired in the latest window.
              </p>
            ) : (
              <FindingsList findings={findings.slice(0, 4)} dense />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Latest AI diagnosis</CardTitle>
              <CardDescription>Reasoning agent output, clearly separated from data</CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href={`/vehicles/${vehicle.id}/diagnosis`}>
                Open
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {agent.isPending ? (
              <Skeleton className="h-24 w-full" />
            ) : agent.isError ? (
              <ErrorState error={agent.error} compact onRetry={() => agent.refetch()} />
            ) : agent.data?.latest_diagnosis ? (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs text-ink-subtle">
                  <Bot className="size-3.5" aria-hidden />
                  {agent.data.latest_diagnosis.generated_at
                    ? new Date(
                        agent.data.latest_diagnosis.generated_at,
                      ).toLocaleString()
                    : "unknown time"}
                  {agent.data.diagnosis_age_seconds !== null ? (
                    <span>· {formatAge(agent.data.diagnosis_age_seconds)} ago</span>
                  ) : null}
                </div>
                <p className="text-sm leading-relaxed text-ink">
                  {agent.data.latest_diagnosis.diagnosis.summary}
                </p>
                {agent.data.latest_diagnosis.execution.fallback_used ? (
                  <InlineAlert tone="attention">
                    Deterministic fallback was used for this diagnosis.
                  </InlineAlert>
                ) : null}
              </>
            ) : (
              <EmptyState
                icon={<ClipboardList className="size-5" aria-hidden />}
                title="No diagnosis yet"
                description={
                  <>
                    The agent explains the health context in plain language with cited
                    sources.{" "}
                    <Link
                      href={`/vehicles/${vehicle.id}/diagnosis`}
                      className="rounded text-signal-400 underline-offset-4 hover:underline"
                    >
                      Ask a question
                    </Link>
                    .
                  </>
                }
                className="border-0 px-0"
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86_400)}d`;
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-3 w-80" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-72 lg:col-span-1" />
        <Skeleton className="h-72 lg:col-span-2" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-56" />
        <Skeleton className="h-56" />
      </div>
      <p className="flex items-center gap-2 text-xs text-ink-subtle">
        <TriangleAlert className="size-3" aria-hidden />
        Loading live vehicle data…
      </p>
    </div>
  );
}

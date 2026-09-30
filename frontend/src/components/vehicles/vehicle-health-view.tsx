"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { Activity, BarChart3, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthSummaryPanel, formatTimestamp } from "@/components/health/health-summary-panel";
import { HealthStatusBadge } from "@/components/health/health-visuals";
import { FindingsList } from "@/components/health/findings-list";
import { useHealthContext } from "@/hooks/use-vehicle-data";
import { useAnalyzeHealth } from "@/hooks/use-mutations";
import { metricLabel } from "@/lib/metrics";
import { cn } from "@/lib/utils";

/**
 * Health page: the full deterministic analysis — score, findings, statistics,
 * trends and baselines, plus the data-quality disclosure.
 */
export function VehicleHealthView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  const health = useHealthContext(vehicleId);
  const analyze = useAnalyzeHealth(vehicleId);
  const context = health.data ?? null;

  return (
    <div className="space-y-4">
      <HealthSummaryPanel
        context={context}
        isAnalyzing={analyze.isPending}
        analyzeError={analyze.isError ? analyze.error : null}
        onAnalyze={(minutes) => analyze.mutate(minutes)}
      />

      {context ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Rule findings</CardTitle>
              <CardDescription>
                Every rule that fired, with the observed value and the threshold that
                triggered it
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <FindingsList findings={context.findings} />
          </CardContent>
        </Card>
      ) : null}

      {context ? (
        <>
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Statistics</CardTitle>
                <CardDescription>
                  Computed over {context.analysis_window.window_minutes} minutes ending{" "}
                  {formatTimestamp(context.analysis_window.end)}
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-2.5">
              {Object.keys(context.statistics).length === 0 ? (
                <p className="text-xs text-ink-subtle">
                  No statistics available — the window contained no samples.
                </p>
              ) : (
                Object.entries(context.statistics).map(([metric, stats]) => (
                  <div
                    key={metric}
                    className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-xs sm:grid-cols-4 lg:grid-cols-7"
                  >
                    <div className="col-span-2 sm:col-span-1">
                      <p className="font-medium text-ink">{metricLabel(metric)}</p>
                      <p className="text-[0.65rem] text-ink-subtle">
                        {stats.unit} · n={stats.count}
                      </p>
                    </div>
                    <Stat label="min" value={stats.minimum} decimals={1} />
                    <Stat label="max" value={stats.maximum} decimals={1} />
                    <Stat label="mean" value={stats.mean} decimals={1} />
                    <Stat label="median" value={stats.median} decimals={1} />
                    <Stat label="std dev" value={stats.std_dev} decimals={2} />
                    <Stat label="last" value={stats.last} decimals={1} />
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Baselines</CardTitle>
                  <CardDescription>
                    Long-term reference values and how the current reading compares
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {context.baselines.length === 0 ? (
                  <p className="text-xs text-ink-subtle">
                    No baseline computed yet — more history is required.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {context.baselines.map((baseline) => (
                      <li
                        key={baseline.metric}
                        className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs"
                      >
                        <span className="text-ink-muted">{metricLabel(baseline.metric)}</span>
                        <span className="tabular text-[0.65rem] text-ink-subtle">
                          current {fmt(baseline.current_value)} vs baseline{" "}
                          {fmt(baseline.center)} {baseline.unit}
                        </span>
                        <span
                          className={cn(
                            "ml-auto rounded border px-1.5 py-0.5 text-[0.62rem] uppercase tracking-wider",
                            baseline.status === "within"
                              ? "border-line text-ink-subtle"
                              : baseline.status === "elevated"
                                ? "border-[color:color-mix(in_oklab,var(--color-attention)_42%,transparent)] text-[color:var(--color-attention)]"
                                : baseline.status === "depressed"
                                  ? "border-[color:color-mix(in_oklab,var(--color-info)_42%,transparent)] text-[color:var(--color-info)]"
                                  : "border-line text-ink-subtle",
                          )}
                        >
                          {baseline.status.replace(/_/g, " ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Data quality</CardTitle>
                  <CardDescription>
                    What the analysis was (and was not) able to see
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-3 text-xs">
                  <QualityFact
                    label="Samples"
                    value={String(context.data_quality.sample_count)}
                  />
                  <QualityFact
                    label="Expected"
                    value={String(context.data_quality.expected_sample_count)}
                  />
                  <QualityFact
                    label="Coverage"
                    value={
                      context.data_quality.coverage_ratio === null
                        ? "unknown"
                        : `${(context.data_quality.coverage_ratio * 100).toFixed(0)}%`
                    }
                  />
                  <QualityFact
                    label="Missing estimate"
                    value={String(context.data_quality.missing_sample_estimate)}
                  />
                  <QualityFact
                    label="Max gap"
                    value={
                      context.data_quality.max_gap_seconds === null
                        ? "—"
                        : `${context.data_quality.max_gap_seconds}s`
                    }
                  />
                  <QualityFact
                    label="Timestamps"
                    value={context.data_quality.timestamp_order_valid ? "in order" : "out of order"}
                  />
                </dl>

                {context.data_quality.coverage_ratio !== null &&
                context.data_quality.coverage_ratio < 0.5 ? (
                  <InlineAlert tone="attention" className="mt-3">
                    Coverage below 50% means the score reflects sparse data. Treat the
                    result as provisional.
                  </InlineAlert>
                ) : null}
                {!context.data_quality.timestamp_order_valid ? (
                  <InlineAlert tone="attention" className="mt-3">
                    Samples arrived out of chronological order, so trend and baseline
                    calculations are less reliable.
                  </InlineAlert>
                ) : null}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Score breakdown</CardTitle>
                <CardDescription>
                  How the {context.score_details.starting_score}-point starting score was
                  reduced
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <HealthStatusBadge status={context.health_status} />
                <span className="tabular text-sm text-ink">
                  {fmt(context.health_score)} / 100
                </span>
                <span className="tabular text-xs text-ink-subtle">
                  −{context.score_details.total_penalty.toFixed(0)} penalty
                </span>
              </div>

              {context.score_details.components.length === 0 ? (
                <p className="text-xs text-ink-subtle">No penalty components applied.</p>
              ) : (
                <ul className="space-y-1.5">
                  {context.score_details.components.map((component) => (
                    <li
                      key={`${component.category}-${component.severity}`}
                      className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs"
                    >
                      <span className="text-ink-muted">{component.category}</span>
                      <span className="text-[0.65rem] uppercase tracking-wider text-ink-subtle">
                        {component.severity} · {component.finding_count} finding
                        {component.finding_count === 1 ? "" : "s"}
                      </span>
                      <span className="tabular ml-auto text-[color:var(--color-attention)]">
                        −{component.penalty.toFixed(0)}
                        {component.capped ? " (capped)" : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {context.score_details.notes.length > 0 ? (
                <ul className="list-disc space-y-0.5 pl-4 text-[0.68rem] text-ink-subtle">
                  {context.score_details.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : health.isPending ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : health.isError ? (
        <ErrorState error={health.error} onRetry={() => health.refetch()} />
      ) : (
        <EmptyState
          icon={<Activity className="size-5" aria-hidden />}
          title="No analysis yet"
          description="Run an analysis to score this vehicle from its recent telemetry. The health engine is deterministic and never calls the AI provider."
        />
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-ink-subtle" aria-hidden />
            <CardTitle>How this score is produced</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-2 text-xs leading-relaxed text-ink-subtle">
          <p>
            The engine applies fixed rules to the statistics of the selected window.
            Each finding contributes a penalty (capped per category) which is
            subtracted from a starting score of{" "}
            <span className="tabular">{context?.score_details.starting_score ?? 100}</span>.
            Rules never call a language model, so the result is reproducible and
            auditable.
          </p>
          <p className="flex items-center gap-1.5">
            <BarChart3 className="size-3" aria-hidden />
            AI interpretation is shown separately, under Diagnosis.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({
  label,
  value,
  decimals,
}: {
  label: string;
  value: number | null;
  decimals: number;
}) {
  return (
    <div>
      <p className="text-[0.62rem] uppercase tracking-wider text-ink-subtle">{label}</p>
      <p className="tabular text-xs text-ink">
        {value === null ? "—" : value.toFixed(decimals)}
      </p>
    </div>
  );
}

function QualityFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.62rem] uppercase tracking-wider text-ink-subtle">{label}</dt>
      <dd className="tabular mt-0.5 text-ink">{value}</dd>
    </div>
  );
}

function fmt(value: number | null): string {
  return value === null ? "—" : value.toFixed(1);
}

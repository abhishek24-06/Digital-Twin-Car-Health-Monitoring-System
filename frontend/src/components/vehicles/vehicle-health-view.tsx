"use client";

import { useParams } from "next/navigation";
import { Activity, BarChart3, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { formatTimestamp } from "@/components/health/health-summary-panel";
import { LiveHealthStatusBody } from "@/components/health/live-health-status";
import { HealthStatusBadge } from "@/components/health/health-visuals";
import { FindingsList } from "@/components/health/findings-list";
import { ContextualPipeline } from "@/components/workflow/contextual-pipeline";
import { useLiveHealth } from "@/hooks/use-vehicle-data";
import { metricLabel, healthStatus } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import type { HealthContextResponse, LiveHealthStatusResponse } from "@/types/api";

/**
 * Live Health page: the current-session assessment for the active simulator
 * run only. The score, findings, statistics, trends and baselines are rendered
 * only when the run is fresh and clears the sufficiency gate; otherwise the
 * page shows honestly why no live verdict exists. Historical windows are a
 * separate concern (Analytics / History) and are never presented here as
 * current health.
 */
export function VehicleHealthView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  const live = useLiveHealth(vehicleId);
  const status = live.data ?? null;
  const assessment = status?.assessment ?? null;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-signal-400">
              <Activity className="size-4" aria-hidden />
            </span>
            <div>
              <CardTitle>Live current-session health</CardTitle>
              <CardDescription>
                The active simulator run only — its score, findings and
                sufficiency. Historical windows live under Analytics and History.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {live.isPending && !status ? (
            <div className="space-y-2.5">
              <Skeleton className="h-16 w-full rounded-lg" />
              <Skeleton className="h-24 w-full rounded-lg" />
            </div>
          ) : live.isError ? (
            <ErrorState error={live.error} onRetry={() => live.refetch()} />
          ) : status ? (
            <LiveHealthStatusBody status={status} />
          ) : null}
        </CardContent>
      </Card>

      <ContextualPipeline id="health" vehicleId={vehicleId} hideWhenEmpty={false} />

      {assessment ? (
        <AssessmentSections context={assessment} />
      ) : live.isPending ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : live.isError ? null : (
        <NoCurrentAssessment status={status} />
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
            The engine applies fixed rules to the statistics of the active run.
            Each finding contributes a penalty (capped per category) which is
            subtracted from a starting score of{" "}
            <span className="tabular">{assessment?.score_details.starting_score ?? 100}</span>.
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

/**
 * The deterministic assessment for the active run. Rendered only when the live
 * gate cleared, so the scope is always the current session.
 */
function AssessmentSections({ context }: { context: HealthContextResponse }) {
  return (
    <>
      <div className="rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-[0.68rem] text-ink-subtle">
        <span className="font-medium text-ink-muted">Report scope</span> ·{" "}
        {context.analysis_scope === "current_session"
          ? "current session"
          : "historical window"}
        {context.simulation_run_id ? (
          <>
            {" "}
            · run{" "}
            <span className="font-mono text-[0.68rem]">{context.simulation_run_id}</span>
          </>
        ) : null}{" "}
        · window {context.analysis_window.window_minutes.toFixed(1)} min (
        {formatTimestamp(context.analysis_window.start)} →{" "}
        {formatTimestamp(context.analysis_window.end)}) · generated{" "}
        {formatTimestamp(context.generated_at)} · latest sample{" "}
        {formatTimestamp(context.data_quality.last_timestamp)}
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Rule findings</CardTitle>
            <CardDescription>
              Every rule that fired for the current run, with the observed value
              and the threshold that triggered it
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <FindingsList findings={context.findings} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Statistics</CardTitle>
            <CardDescription>
              Computed over {context.analysis_window.window_minutes.toFixed(1)} minutes
              ending {formatTimestamp(context.analysis_window.end)}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-2.5">
          {Object.keys(context.statistics).length === 0 ? (
            <p className="text-xs text-ink-subtle">
              No statistics available — the run had no samples in the window.
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
                Long-term reference values and how the current run compares
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
                What the current-session analysis was (and was not) able to see
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-3 text-xs">
              <QualityFact label="Samples" value={String(context.data_quality.sample_count)} />
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
            <span className="tabular text-sm text-ink">{fmt(context.health_score)} / 100</span>
            <span className="tabular text-xs text-ink-subtle">
              −{context.score_details.total_penalty.toFixed(0)} penalty
            </span>
          </div>

          {context.provisional ? (
            <div className="mt-3 space-y-2 rounded-md border border-line bg-surface-2 px-3 py-2.5 text-xs">
              <p className="text-ink">
                Provisional assessment — based on limited telemetry, treated as
                low-confidence until more data arrives.
              </p>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                <div className="flex items-center gap-2">
                  <dt className="text-ink-subtle">Provisional rating</dt>
                  <dd>
                    <HealthStatusBadge
                      status={context.provisional_rating ?? context.score_details.status}
                      size="sm"
                    />
                  </dd>
                </div>
                <div className="flex items-center gap-1">
                  <dt className="text-ink-subtle">Confidence</dt>
                  <dd className="tabular">
                    {context.confidence === null
                      ? "—"
                      : `${(context.confidence * 100).toFixed(0)}%`}
                  </dd>
                </div>
                <div className="flex items-center gap-1">
                  <dt className="text-ink-subtle">Samples</dt>
                  <dd className="tabular">{context.data_quality.sample_count}</dd>
                </div>
                <div className="flex items-center gap-1">
                  <dt className="text-ink-subtle">Coverage</dt>
                  <dd className="tabular">
                    {context.data_quality.coverage_ratio === null
                      ? "—"
                      : `${(context.data_quality.coverage_ratio * 100).toFixed(0)}%`}
                  </dd>
                </div>
              </dl>
              <p className="text-[0.68rem] text-ink-subtle">
                {healthStatus(context.score_details.status).label} is the best
                available reading; it is not a definitive verdict.
              </p>
            </div>
          ) : null}

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
  );
}

/**
 * The honest "no current verdict" state. A stopped session, a collecting run or
 * a stale feed never reuses an old snapshot as if it were current health.
 */
function NoCurrentAssessment({ status }: { status: LiveHealthStatusResponse | null }) {
  const state = status?.live_state;
  const title =
    state === "no_session"
      ? "No active session"
      : state === "collecting"
        ? "Collecting current-session data"
        : state === "stale"
          ? "Current-session feed is stale"
          : "No current-session assessment";
  const description =
    state === "no_session"
      ? "There is no active simulator run, so there is no current session to score. Historical evidence stays available under Analytics and History."
      : state === "collecting"
        ? "The active run has not yet collected enough fresh evidence to score. The live view stays provisional until the sufficiency gate clears."
        : state === "stale"
          ? "The active run's newest sample is older than the freshness limit, so the current-session assessment is withheld rather than reused."
          : "A current-session assessment is not available right now.";
  return (
    <EmptyState
      icon={<Activity className="size-5" aria-hidden />}
      title={title}
      description={description}
    />
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

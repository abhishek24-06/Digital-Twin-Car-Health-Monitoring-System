"use client";

import * as React from "react";
import { Activity } from "lucide-react";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { InlineAlert } from "@/components/states/feedback";
import { HealthStatusBadge } from "@/components/health/health-visuals";
import { formatDuration, formatPercent, formatRelative, formatTime } from "@/lib/format";
import type {
  LiveFreshnessState,
  LiveHealthStatusResponse,
  SimulationState,
} from "@/types/api";
import { cn } from "@/lib/utils";

const SIM_STATE_TONE: Record<SimulationState, NonNullable<BadgeProps["tone"]>> = {
  stopped: "neutral",
  starting: "attention",
  running: "healthy",
  stopping: "attention",
  degraded: "attention",
  error: "critical",
};

const LIVE_STATE_TONE: Record<LiveFreshnessState, NonNullable<BadgeProps["tone"]>> = {
  no_session: "neutral",
  no_data: "neutral",
  collecting: "accent",
  stale: "attention",
  fresh: "healthy",
};

const LIVE_STATE_LABEL: Record<LiveFreshnessState, string> = {
  no_session: "no session",
  no_data: "no data",
  collecting: "collecting data",
  stale: "stale feed",
  fresh: "fresh",
};

/**
 * Honest live current-session view: the simulator state, the run identity, the
 * data-freshness state and -- once enough fresh current-run evidence exists --
 * the definitive assessment. A stopped vehicle, a collecting session or a
 * stale feed is shown as-is, never as a historical snapshot dressed up as
 * current. Shared by the Simulation tab and the Live Health tab so both tell
 * the same story.
 */
export function LiveHealthStatusBody({ status }: { status: LiveHealthStatusResponse }) {
  const hasRun = status.run_id !== null;
  const assessment = status.assessment;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={SIM_STATE_TONE[status.simulator_state]} size="sm">
          simulator {status.simulator_state}
        </Badge>
        <Badge tone={LIVE_STATE_TONE[status.live_state]} size="sm">
          {LIVE_STATE_LABEL[status.live_state]}
        </Badge>
        {assessment ? (
          <>
            <HealthStatusBadge status={assessment.health_status} size="sm" />
            <span className="text-xs text-ink-muted">
              definitive live assessment
            </span>
          </>
        ) : null}
      </div>

      {status.message ? (
        <InlineAlert
          tone={
            status.live_state === "stale"
              ? "attention"
              : status.live_state === "fresh"
                ? "info"
                : "info"
          }
          title={
            status.live_state === "stale"
              ? "Current-session feed is stale"
              : status.live_state === "no_session"
                ? "No active simulator run"
                : status.live_state === "collecting"
                  ? "Collecting current-run data"
                  : "Live assessment current"
          }
        >
          {status.message}
        </InlineAlert>
      ) : null}

      {assessment ? (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-xs">
          <div className="flex items-center gap-2">
            <span className="tabular text-lg font-semibold text-ink">
              {assessment.health_score?.toFixed(1) ?? "—"}
            </span>
            <span className="text-ink-subtle">/ 100</span>
          </div>
          <Fact label="Confidence" value={formatPercent(assessment.confidence)} />
          <Fact label="Assessed at" value={formatTime(assessment.generated_at)} />
          <Fact
            label="Window"
            value={`${formatDuration(
              (new Date(assessment.analysis_window.end).getTime() -
                new Date(assessment.analysis_window.start).getTime()) /
                1000,
            )} ending ${formatTime(assessment.analysis_window.end)}`}
          />
        </div>
      ) : null}

      {hasRun ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs sm:grid-cols-3">
          <RunFact
            label="Run id"
            value={
              <span className="block max-w-40 truncate font-mono text-[0.7rem]">
                {status.run_id}
              </span>
            }
          />
          <RunFact
            label="Current-run samples"
            value={
              <span className="tabular">
                {status.sample_count}{" "}
                <span className="text-ink-subtle">
                  / {status.required_sample_count} required
                </span>
              </span>
            }
          />
          <RunFact
            label="Observation duration"
            value={
              status.observation_duration_seconds === null ? (
                <span>—</span>
              ) : (
                <span className="tabular">
                  {formatDuration(status.observation_duration_seconds)}{" "}
                  <span className="text-ink-subtle">
                    / {formatDuration(status.required_duration_seconds)} needed
                  </span>
                </span>
              )
            }
          />
          <RunFact
            label="Coverage"
            value={
              status.coverage_ratio === null ? (
                <span>—</span>
              ) : (
                <span className="tabular">
                  {formatPercent(status.coverage_ratio)}{" "}
                  <span className="text-ink-subtle">
                    / {formatPercent(status.required_coverage)} needed
                  </span>
                </span>
              )
            }
          />
          <RunFact
            label="Newest sample age"
            value={
              status.latest_sample_age_seconds === null ? (
                <span>—</span>
              ) : (
                <span
                  className={cn(
                    "tabular",
                    status.latest_sample_age_seconds > status.max_sample_age_seconds
                      ? "text-[color:var(--color-attention)]"
                      : undefined,
                  )}
                >
                  {formatDuration(status.latest_sample_age_seconds)}{" "}
                  <span className="text-ink-subtle">
                    / {formatDuration(status.max_sample_age_seconds)}
                  </span>
                </span>
              )
            }
          />
          <RunFact
            label="Latest sample"
            value={
              status.latest_source_timestamp === null ? (
                <span>—</span>
              ) : (
                <span className="tabular">
                  {formatRelative(status.latest_source_timestamp)}
                </span>
              )
            }
          />
          <RunFact
            label="Persisted at"
            value={
              status.latest_persisted_at === null ? (
                <span>—</span>
              ) : (
                <span className="tabular">
                  {formatTime(status.latest_persisted_at)}
                </span>
              )
            }
          />
          <RunFact
            label="Last evaluation"
            value={
              status.last_evaluated_at === null ? (
                <span>—</span>
              ) : (
                <span className="tabular">
                  {formatRelative(status.last_evaluated_at)}
                </span>
              )
            }
          />
          <RunFact
            label="Timestamps"
            value={status.sample_timestamp_order_valid ? "in order" : "out of order"}
          />
        </dl>
      ) : (
        <p className="flex items-center gap-1.5 text-xs text-ink-muted">
          <Activity className="size-3.5" aria-hidden />
          No simulator run is active for this vehicle, so there is no current
          session to assess. Historical evidence stays available under Analytics
          and History.
        </p>
      )}

      {!assessment && status.insufficiency_reasons.length > 0 && hasRun ? (
        <div className="space-y-1 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-xs text-ink-subtle">
          <p className="font-medium text-ink-muted">
            Why the live view is not definitive yet
          </p>
          <ul className="list-disc space-y-0.5 pl-4">
            {status.insufficiency_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.62rem] uppercase tracking-wider text-ink-subtle">{label}</p>
      <p className="tabular text-xs text-ink">{value}</p>
    </div>
  );
}

function RunFact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.62rem] uppercase tracking-wider text-ink-subtle">{label}</dt>
      <dd className="mt-0.5 text-ink">{value}</dd>
    </div>
  );
}

"use client";

import * as React from "react";
import { Activity, Clock, Database, PlayCircle, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { SelectMenu } from "@/components/ui/select-menu";
import { ErrorState } from "@/components/states/feedback";
import { HealthScoreRing, HealthStatusBadge } from "@/components/health/health-visuals";
import { ANALYSIS_WINDOWS } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import type { HealthContextResponse } from "@/types/api";

/**
 * Health summary panel: score, status, data-quality facts and the deterministic
 * "Analyze" action. When no snapshot exists the panel becomes a call to action
 * instead of an error (the API returns 404 in that case).
 */
export function HealthSummaryPanel({
  context,
  isAnalyzing,
  analyzeError,
  onAnalyze,
  className,
}: {
  context: HealthContextResponse | null;
  isAnalyzing: boolean;
  analyzeError: unknown;
  onAnalyze: (windowMinutes?: number) => void;
  className?: string;
}) {
  const [windowMinutes, setWindowMinutes] = React.useState<string>("60");
  const windowOptions = ANALYSIS_WINDOWS.map((minutes) => ({
    value: String(minutes),
    label: minutes >= 1440 ? "24 hours" : minutes >= 60 ? `${minutes / 60} hour${minutes > 60 ? "s" : ""}` : `${minutes} min`,
  }));

  if (!context) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Vehicle health</CardTitle>
          <CardDescription>
            No health snapshot has been generated for this vehicle yet.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col items-center gap-4 rounded-lg border border-dashed border-line px-6 py-8 text-center sm:flex-row sm:text-left">
            <HealthScoreRing score={null} status="unknown" size={132} />
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-ink">No analysis yet</p>
              <p className="max-w-sm text-xs leading-relaxed text-ink-subtle">
                Running an analysis scores the vehicle from its recent telemetry
                using the deterministic rule engine. It never contacts the AI
                provider.
              </p>
              <div className="pt-1">
                <Button
                  size="sm"
                  loading={isAnalyzing}
                  onClick={() => onAnalyze(Number(windowMinutes))}
                >
                  <PlayCircle aria-hidden />
                  Run health analysis
                </Button>
              </div>
            </div>
          </div>
          {analyzeError ? <ErrorState error={analyzeError} compact /> : null}
        </CardContent>
      </Card>
    );
  }

  const quality = context.data_quality;
  const coverage =
    quality.coverage_ratio === null ? null : quality.coverage_ratio * 100;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Vehicle health</CardTitle>
        <CardDescription>
          Deterministic rule-engine score · schema {context.context_schema_version} · engine{" "}
          {context.rule_engine_version}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center">
          <HealthScoreRing score={context.health_score} status={context.health_status} />

          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <HealthStatusBadge status={context.health_status} size="lg" />
              {context.confidence !== null ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-2.5 py-1 text-xs text-ink-muted">
                  confidence {(context.confidence * 100).toFixed(0)}%
                </span>
              ) : null}
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs sm:grid-cols-3">
              <Fact
                icon={Clock}
                label="Generated"
                value={formatTimestamp(context.generated_at)}
              />
              <Fact
                icon={Database}
                label="Samples"
                value={String(quality.sample_count)}
              />
              <Fact
                icon={Activity}
                label="Coverage"
                value={coverage === null ? "unknown" : `${coverage.toFixed(0)}%`}
              />
            </dl>

            {context.score_details.total_penalty > 0 ? (
              <p className="text-xs text-ink-subtle">
                Score reduced by{" "}
                <span className="tabular font-medium text-[color:var(--color-attention)]">
                  {context.score_details.total_penalty.toFixed(0)} points
                </span>{" "}
                from {context.score_details.starting_score}.
              </p>
            ) : (
              <p className="text-xs text-ink-subtle">
                No penalties applied — full score retained.
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3 border-t border-line pt-4">
          <div className="w-full sm:w-48">
            <label
              htmlFor="analysis-window"
              className="mb-1.5 block text-xs font-medium text-ink-muted"
            >
              Analysis window
            </label>
            <SelectMenu
              value={windowMinutes}
              options={windowOptions}
              onChange={setWindowMinutes}
              label="Analysis window"
            />
          </div>
          <Button
            variant="outline"
            loading={isAnalyzing}
            onClick={() => onAnalyze(Number(windowMinutes))}
          >
            <PlayCircle aria-hidden />
            Re-run analysis
          </Button>
          <p className="text-[0.68rem] text-ink-subtle">
            Window{" "}
            <span className="tabular">
              {context.analysis_window.window_minutes} min
            </span>{" "}
            ending {formatTimestamp(context.analysis_window.end)}
          </p>
        </div>

        {analyzeError ? <ErrorState error={analyzeError} compact /> : null}

        {quality.sample_count === 0 ? (
          <div className="flex gap-2.5 rounded-lg border border-[color:color-mix(in_oklab,var(--color-attention)_34%,transparent)] bg-[color:color-mix(in_oklab,var(--color-attention)_8%,transparent)] px-3 py-2.5">
            <TriangleAlert
              className="mt-0.5 size-4 shrink-0 text-[color:var(--color-attention)]"
              aria-hidden
            />
            <p className="text-xs leading-relaxed text-ink-muted">
              The window contains no telemetry samples, so the score reflects the
              absence of data rather than the vehicle&apos;s condition.
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Fact({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock;
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[0.65rem] uppercase tracking-wider text-ink-subtle">
        <Icon className="size-3" aria-hidden />
        {label}
      </dt>
      <dd className={cn("tabular mt-0.5 truncate text-xs text-ink")}>{value}</dd>
    </div>
  );
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

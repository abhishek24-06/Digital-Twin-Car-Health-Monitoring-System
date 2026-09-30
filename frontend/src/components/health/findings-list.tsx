"use client";

import * as React from "react";
import { ChevronRight, Gauge, Wrench } from "lucide-react";
import { SeverityBadge } from "@/components/health/health-visuals";
import { metricLabel, metricMeta } from "@/lib/metrics";
import { SEVERITY_RANK } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import type { Finding } from "@/types/api";

/**
 * Deterministic rule findings from the health engine.
 *
 * These come from `HealthContextResponse.findings`, i.e. the rule engine — never
 * from the LLM. Each finding shows the observed value against the threshold that
 * triggered it so a driver can judge it themselves.
 */
export function FindingsList({
  findings,
  className,
  dense = false,
}: {
  findings: readonly Finding[];
  className?: string;
  dense?: boolean;
}) {
  const sorted = React.useMemo(
    () =>
      [...findings].sort(
        (a, b) =>
          SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
          a.category.localeCompare(b.category),
      ),
    [findings],
  );

  if (sorted.length === 0) {
    return (
      <p className={cn("text-xs leading-relaxed text-ink-subtle", className)}>
        No rule fired in this window. Every monitored metric stayed inside its
        expected range.
      </p>
    );
  }

  return (
    <ul className={cn("space-y-2", className)}>
      {sorted.map((finding, index) => (
        <li key={`${finding.rule_id}-${finding.metric ?? "none"}-${index}`}>
          <FindingRow finding={finding} dense={dense} />
        </li>
      ))}
    </ul>
  );
}

function FindingRow({ finding, dense }: { finding: Finding; dense: boolean }) {
  const meta = finding.metric ? metricMeta(finding.metric) : undefined;
  const decimals = meta?.decimals ?? 1;

  return (
    <details className="group rounded-lg border border-line bg-surface-2 transition-colors open:border-line-strong">
      <summary className="flex cursor-pointer list-none items-start gap-2.5 rounded-lg px-3 py-2.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400">
        <ChevronRight
          className="mt-0.5 size-3.5 shrink-0 text-ink-subtle transition-transform group-open:rotate-90"
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <SeverityBadge severity={finding.severity} />
            <span className="text-xs text-ink-muted">{finding.category}</span>
            {finding.metric ? (
              <span className="rounded border border-line px-1 text-[0.62rem] text-ink-subtle">
                {metricLabel(finding.metric)}
              </span>
            ) : null}
          </span>
          <span className="mt-1.5 block text-sm leading-snug text-ink">
            {finding.message}
          </span>
          {!dense ? (
            <span className="tabular mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.68rem] text-ink-subtle">
              {finding.observed_value !== null ? (
                <span>
                  observed{" "}
                  <span className="font-medium text-ink-muted">
                    {finding.observed_value.toFixed(decimals)}
                    {finding.unit ?? meta?.unit ? ` ${finding.unit ?? meta?.unit}` : ""}
                  </span>
                </span>
              ) : null}
              {finding.threshold !== null ? (
                <span>
                  threshold{" "}
                  <span className="font-medium text-ink-muted">
                    {finding.threshold.toFixed(decimals)}
                    {finding.unit ?? meta?.unit ? ` ${finding.unit ?? meta?.unit}` : ""}
                  </span>
                </span>
              ) : null}
              {finding.confidence !== null ? (
                <span>
                  confidence{" "}
                  <span className="font-medium text-ink-muted">
                    {(finding.confidence * 100).toFixed(0)}%
                  </span>
                </span>
              ) : null}
            </span>
          ) : null}
        </span>
      </summary>

      <div className="border-t border-line px-3 py-2.5 text-xs text-ink-subtle">
        <p className="mb-1.5 font-mono text-[0.65rem] uppercase tracking-wider">
          {finding.rule_id}
        </p>
        {finding.window_start && finding.window_end ? (
          <p className="mb-1.5">
            window {formatTime(finding.window_start)} → {formatTime(finding.window_end)}
          </p>
        ) : null}
        {Object.keys(finding.evidence ?? {}).length > 0 ? (
          <details className="group/ev">
            <summary className="inline-flex cursor-pointer items-center gap-1 rounded text-[0.68rem] text-ink-muted hover:text-ink">
              <Gauge className="size-3" aria-hidden />
              rule evidence
            </summary>
            <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[0.65rem]">
              {Object.entries(finding.evidence ?? {}).map(([key, value]) => (
                <React.Fragment key={key}>
                  <dt className="text-ink-subtle">{key}</dt>
                  <dd className="break-all text-ink-muted">{renderValue(value)}</dd>
                </React.Fragment>
              ))}
            </dl>
          </details>
        ) : null}
      </div>
    </details>
  );
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(3);
  }
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compact list of suggested next steps, ordered by priority. */
export function ActionHints({ hints }: { hints: readonly string[] }) {
  if (hints.length === 0) return null;
  return (
    <ul className="space-y-1.5">
      {hints.map((hint) => (
        <li key={hint} className="flex gap-2 text-xs leading-relaxed text-ink-muted">
          <Wrench className="mt-0.5 size-3 shrink-0 text-ink-subtle" aria-hidden />
          <span>{hint}</span>
        </li>
      ))}
    </ul>
  );
}

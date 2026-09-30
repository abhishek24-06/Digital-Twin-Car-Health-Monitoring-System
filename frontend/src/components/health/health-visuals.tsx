"use client";

import { createElement } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  type LucideIcon,
} from "lucide-react";
import { healthStatus, type StatusSemantics } from "@/lib/metrics";
import type { HealthStatus, Severity } from "@/types/api";
import { cn } from "@/lib/utils";

/**
 * Health status is communicated three ways at once — icon, text label and
 * colour — so the state is never conveyed by colour alone.
 */
export function HealthStatusBadge({
  status,
  size = "md",
  className,
}: {
  status: HealthStatus | null | undefined;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const semantics = healthStatus(status);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium",
        semantics.border,
        semantics.surface,
        semantics.text,
        size === "sm" ? "px-2 py-0.5 text-[0.68rem]" : "px-2.5 py-1 text-xs",
        className,
      )}
    >
      <StatusIcon status={status} className={cn(size === "lg" ? "size-4" : "size-3.5")} />
      {semantics.label}
    </span>
  );
}

/** Icon for a health status. Switched inline so no component is built in render. */
export function StatusIcon({
  status,
  className,
}: {
  status: HealthStatus | null | undefined;
  className?: string;
}) {
  switch (status) {
    case "healthy":
      return <CheckCircle2 className={className} aria-hidden />;
    case "attention":
      return <AlertTriangle className={className} aria-hidden />;
    case "critical":
      return <AlertOctagon className={className} aria-hidden />;
    default:
      return <CircleHelp className={className} aria-hidden />;
  }
}

export const SEVERITY_ICON: Record<Severity, LucideIcon> = {
  info: CircleHelp,
  warning: AlertTriangle,
  critical: AlertOctagon,
};

export const SEVERITY_COLOR: Record<Severity, string> = {
  info: "var(--color-info)",
  warning: "var(--color-attention)",
  critical: "var(--color-critical)",
};

export function SeverityBadge({
  severity,
  className,
}: {
  severity: Severity;
  className?: string;
}) {
  const tone =
    severity === "critical"
      ? "critical"
      : severity === "warning"
        ? "attention"
        : "accent";
  const label =
    severity === "info" ? "Info" : severity === "warning" ? "Warning" : "Critical";

  const icon = SEVERITY_ICON[severity];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[0.65rem] font-medium",
        tone === "critical"
          ? "border-[color:color-mix(in_oklab,var(--color-critical)_42%,transparent)] bg-[color:color-mix(in_oklab,var(--color-critical)_14%,transparent)] text-[color:var(--color-critical)]"
          : tone === "attention"
            ? "border-[color:color-mix(in_oklab,var(--color-attention)_42%,transparent)] bg-[color:color-mix(in_oklab,var(--color-attention)_14%,transparent)] text-[color:var(--color-attention)]"
            : "border-[color:color-mix(in_oklab,var(--color-info)_42%,transparent)] bg-[color:color-mix(in_oklab,var(--color-info)_14%,transparent)] text-[color:var(--color-info)]",
        className,
      )}
    >
      {createElement(icon, { className: "size-3", "aria-hidden": true })}
      {label}
    </span>
  );
}

/** Coloured arc + numeric score. Pure SVG so it works without a chart lib. */
export function HealthScoreRing({
  score,
  status,
  size = 168,
  strokeWidth = 12,
  label,
}: {
  score: number | null;
  status: HealthStatus | null | undefined;
  size?: number;
  strokeWidth?: number;
  label?: string;
}) {
  const semantics: StatusSemantics = healthStatus(status);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const hasScore = typeof score === "number" && !Number.isNaN(score);
  const clamped = hasScore ? Math.max(0, Math.min(100, score)) : 0;
  const offset = circumference * (1 - clamped / 100);

  return (
    <div
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={
        hasScore
          ? `Health score ${clamped.toFixed(0)} out of 100 — ${semantics.label}`
          : "Health score unavailable — insufficient data"
      }
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--surface-3)"
          strokeWidth={strokeWidth}
        />
        {hasScore ? (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={semantics.color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            style={{ transition: "stroke-dashoffset 600ms cubic-bezier(0.22,1,0.36,1)" }}
          />
        ) : null}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className={cn(
            "tabular text-3xl font-semibold tracking-tight",
            hasScore ? semantics.text : "text-ink-subtle",
          )}
        >
          {hasScore ? clamped.toFixed(0) : "—"}
        </span>
        <span className="mt-0.5 text-[0.65rem] uppercase tracking-widest text-ink-subtle">
          {label ?? "of 100"}
        </span>
      </div>
    </div>
  );
}

"use client";

import * as React from "react";
import { Loader2, Wifi, WifiOff, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelative } from "@/lib/format";
import type { WorkflowEventResponse } from "@/types/api";
import type { DerivedStageState, StageDef } from "./pipelines";
import { WorkflowStatusBadge, type StageStatus } from "./status";
import type { WorkflowConnection } from "./workflow-stream-provider";

export interface WorkflowPipelineStepProps {
  label: string;
  status: StageStatus;
  /** Human-readable, honest explanation of how the state was observed. */
  detail?: string;
  lastEvent?: WorkflowEventResponse | null;
  icon?: React.ReactNode;
  /** 1-based position within the pipeline; shown so a wrapped grid still reads in order. */
  position?: number;
  /** When the most recent signal for this stage was observed (ISO-8601 UTC). */
  at?: string | null;
}

/**
 * One node of a pipeline. Thin and presentational: the parent decides what the
 * status is and where it came from; this component never invents progress.
 */
export function WorkflowPipelineStep({
  label,
  status,
  detail,
  lastEvent,
  icon,
  position,
  at,
}: WorkflowPipelineStepProps) {
  return (
    <li className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface-1 p-3">
      {/*
        Title row: number + icon + wrapping title. The status badge lives in its
        own row below so it can never overlap the title/icon or spill out of a
        narrow column (the previous single-row layout overflowed the card and
        caused the whole page to scroll horizontally).
      */}
      <div className="flex min-w-0 items-start gap-2">
        {position !== undefined ? (
          <span
            className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-2 text-[0.65rem] font-semibold text-ink-subtle"
            aria-hidden="true"
          >
            {position}
          </span>
        ) : null}
        {icon ? <span className="mt-0.5 shrink-0 text-ink-subtle">{icon}</span> : null}
        <span className="min-w-0 flex-1 text-sm font-medium leading-snug break-words text-ink">
          {label}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <WorkflowStatusBadge status={status} />
        {at ? (
          <time dateTime={at} className="text-[0.65rem] text-ink-subtle">
            {formatRelative(at)}
          </time>
        ) : null}
      </div>

      {detail ? (
        <p className="text-xs leading-snug break-words text-ink-muted">{detail}</p>
      ) : null}
      {lastEvent ? (
        <p className="text-xs leading-snug break-words text-ink-subtle">
          {lastEvent.message}
        </p>
      ) : null}
    </li>
  );
}

export interface WorkflowPipelineProps {
  title?: string;
  steps: React.ReactNode;
  orientation?: "horizontal" | "vertical";
  /** Optional trailing affordance in the title row (e.g. a live indicator). */
  header?: React.ReactNode;
  className?: string;
}

/**
 * Ordered set of pipeline steps. Horizontal pipelines wrap into a responsive
 * grid so a long pipeline such as telemetry's eight stages never squeezes into
 * unreadable slivers: one column on phones, two on tablets, and four only once
 * the viewport (and therefore the vehicle card) is wide enough for four
 * readable columns. Every stage has `min-width: 0` and wraps its text.
 */
export function WorkflowPipeline({
  title,
  steps,
  orientation = "horizontal",
  header,
  className,
}: WorkflowPipelineProps) {
  return (
    <section className={cn("flex min-w-0 flex-col gap-2", className)}>
      {title || header ? (
        <div className="flex items-center justify-between gap-2">
          {title ? (
            <h3 className="text-sm font-semibold text-ink">{title}</h3>
          ) : (
            <span />
          )}
          {header}
        </div>
      ) : null}
      <ol
        role="list"
        className={cn(
          "grid min-w-0 grid-cols-1 gap-3",
          orientation === "horizontal" && "sm:grid-cols-2 xl:grid-cols-4",
        )}
      >
        {steps}
      </ol>
    </section>
  );
}

const CONNECTION_META: Record<
  WorkflowConnection,
  { label: string; icon: LucideIcon; className: string }
> = {
  connecting: {
    label: "Connecting",
    icon: Loader2,
    className: "text-ink-muted",
  },
  live: {
    label: "Live",
    icon: Wifi,
    className: "text-[color:var(--color-healthy)]",
  },
  reconnecting: {
    label: "Reconnecting",
    icon: Loader2,
    className: "text-[color:var(--color-attention)]",
  },
  disconnected: {
    label: "Disconnected",
    icon: WifiOff,
    className: "text-[color:var(--color-critical)]",
  },
};

/**
 * Convenience renderer for a registry pipeline: joins derived stage states with
 * their stage definitions (labels + icons) so feature panels stay thin.
 */
export function WorkflowPipelineSteps({
  stages,
  states,
}: {
  stages: StageDef[];
  states: DerivedStageState[];
}) {
  return (
    <>
      {states.map((state, index) => {
        const def = stages.find((stage) => stage.key === state.stage);
        const Icon = def?.icon;
        return (
          <WorkflowPipelineStep
            key={state.stage}
            position={index + 1}
            label={state.label}
            status={state.status}
            detail={state.detail}
            at={state.at}
            lastEvent={state.lastEvent}
            icon={Icon ? <Icon className="size-5" aria-hidden="true" /> : undefined}
          />
        );
      })}
    </>
  );
}

/**
 * Shared live-connection affordance. Text + icon, never colour alone.
 */
export function WorkflowConnectionIndicator({
  status,
}: {
  status: WorkflowConnection;
}) {
  const meta = CONNECTION_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium",
        meta.className,
      )}
      aria-label={`Stream ${meta.label}`}
    >
      <Icon
        className={cn("size-3", status === "connecting" || status === "reconnecting" ? "animate-spin" : undefined)}
        aria-hidden="true"
      />
      <span>{meta.label}</span>
    </span>
  );
}

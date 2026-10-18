"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { FleetTone } from "@/lib/fleet";
import { formatRelative } from "@/lib/format";
import type {
  FleetTotals,
  HealthDbResponse,
  HealthResponse,
  WorkflowStatusResponse,
} from "@/types/api";

/** Structural subset of a TanStack query result, so callers pass the real one. */
export interface Probe<T> {
  isPending: boolean;
  isError: boolean;
  data?: T;
}

type Availability = "available" | "unavailable" | "unknown";

const AVAILABILITY: Record<Availability, { label: string; tone: FleetTone }> = {
  available: { label: "Available", tone: "healthy" },
  unavailable: { label: "Unavailable", tone: "critical" },
  unknown: { label: "Unknown", tone: "unknown" },
};

interface StatusRow {
  key: string;
  label: string;
  value: string;
  tone: FleetTone;
  detail: string;
}

function livenessRow(probe: Probe<HealthResponse>): StatusRow {
  const state: Availability = probe.isPending
    ? "unknown"
    : probe.isError || probe.data?.status !== "ok"
      ? "unavailable"
      : "available";
  return {
    key: "api",
    label: "API service",
    value: AVAILABILITY[state].label,
    tone: AVAILABILITY[state].tone,
    detail:
      state === "available"
        ? "The backend process answered its liveness check."
        : state === "unavailable"
          ? "The API did not answer — data below may be out of date."
          : "Checking…",
  };
}

function databaseRow(probe: Probe<HealthDbResponse>): StatusRow {
  const state: Availability = probe.isPending
    ? "unknown"
    : probe.isError || probe.data?.database !== "ok"
      ? "unavailable"
      : "available";
  return {
    key: "db",
    label: "Database",
    value: AVAILABILITY[state].label,
    tone: AVAILABILITY[state].tone,
    detail:
      state === "available"
        ? "The persistence layer answered a SELECT 1."
        : state === "unavailable"
          ? "Stored telemetry, scores and alerts cannot be read right now."
          : "Checking…",
  };
}

function ingestionRow(probe: Probe<WorkflowStatusResponse>): StatusRow {
  if (probe.isPending || probe.isError || !probe.data) {
    return {
      key: "ingestion",
      label: "Telemetry ingestion",
      value: "Unknown",
      tone: "unknown",
      detail: "The MQTT subscriber state could not be read.",
    };
  }
  const running = probe.data.subscriber_running;
  return {
    key: "ingestion",
    label: "Telemetry ingestion",
    value: running ? "Running" : "Stopped",
    tone: running ? "healthy" : "attention",
    detail: running
      ? "The MQTT subscriber is consuming simulator output."
      : "The subscriber is not running, so published telemetry is not being stored.",
  };
}

function flowRow(totals: FleetTotals | null): StatusRow {
  if (!totals) {
    return {
      key: "flow",
      label: "Fleet telemetry flow",
      value: "Unknown",
      tone: "unknown",
      detail: "The fleet snapshot could not be read, so flow is unknown.",
    };
  }
  if (totals.vehicles === 0) {
    return {
      key: "flow",
      label: "Fleet telemetry flow",
      value: "No vehicles",
      tone: "neutral",
      detail: "Register a vehicle to start collecting telemetry.",
    };
  }
  const live = totals.vehicles_with_recent_telemetry;
  return {
    key: "flow",
    label: "Fleet telemetry flow",
    value: live > 0 ? `${live} of ${totals.vehicles} live` : "Idle",
    tone: live > 0 ? "healthy" : "neutral",
    detail:
      live > 0
        ? "At least one vehicle is producing fresh telemetry."
        : "No vehicle has produced a sample inside the freshness window.",
  };
}

/**
 * Availability and activity, kept strictly separate.
 *
 * API liveness, database reachability, MQTT ingestion, telemetry flow and
 * simulator activity are independent signals: none is inferred from another, and
 * a probe that cannot be read is shown as "Unknown" rather than assumed healthy.
 */
export function PlatformStatus({
  liveness,
  database,
  workflow,
  totals,
  generatedAt,
}: {
  liveness: Probe<HealthResponse>;
  database: Probe<HealthDbResponse>;
  workflow: Probe<WorkflowStatusResponse>;
  totals: FleetTotals | null;
  generatedAt: string | null;
}) {
  const rows: StatusRow[] = [
    livenessRow(liveness),
    databaseRow(database),
    ingestionRow(workflow),
    flowRow(totals),
    {
      key: "sims",
      label: "Active simulators",
      value: totals ? String(totals.active_simulations) : "—",
      tone: totals && totals.active_simulations > 0 ? "healthy" : "neutral",
      detail: "Simulators starting, running or stopping across your fleet.",
    },
  ];

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Platform &amp; pipeline</CardTitle>
          <CardDescription>
            Independent health signals — availability is never inferred from a
            successful request alone.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => (
            <div key={row.key} className="flex items-start justify-between gap-3" data-testid={`platform-${row.key}`}>
              <div className="min-w-0">
                <dt className="text-xs font-medium text-ink-muted">{row.label}</dt>
                <dd className="mt-0.5 text-[0.7rem] leading-relaxed text-ink-subtle">
                  {row.detail}
                </dd>
              </div>
              <Badge tone={row.tone} size="sm" className="mt-0.5 shrink-0">
                {row.value}
              </Badge>
            </div>
          ))}
        </dl>
        {generatedAt ? (
          <p className="mt-4 border-t border-line pt-3 text-[0.7rem] text-ink-subtle">
            Fleet snapshot read {formatRelative(generatedAt)}.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function PlatformStatusSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-4 w-40" />
      </CardHeader>
      <CardContent className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  );
}

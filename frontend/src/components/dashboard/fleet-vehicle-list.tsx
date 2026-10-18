"use client";

import Link from "next/link";
import { ArrowRight, BellRing, CirclePlay, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineAlert } from "@/components/states/feedback";
import { HealthScoreRing, HealthStatusBadge } from "@/components/health/health-visuals";
import {
  ASSESSMENT_FRESHNESS,
  SIMULATOR_STATE,
  TELEMETRY_FRESHNESS,
  assessmentRating,
  attentionReason,
} from "@/lib/fleet";
import { formatDateTime, formatPercent, formatRelative, maskVin, titleCase } from "@/lib/format";
import type { FleetAssessmentSummary, FleetVehicleSummary } from "@/types/api";

/**
 * The fleet list.
 *
 * A single vehicle gets a wider card with its health score; a multi-vehicle
 * fleet gets a responsive grid that stays scannable as it grows. Every fact is
 * read from the backend snapshot — nothing is derived in the browser.
 */
export function FleetVehicleList({
  vehicles,
  telemetryStaleAfterSeconds,
  assessmentStaleAfterSeconds,
}: {
  vehicles: FleetVehicleSummary[];
  telemetryStaleAfterSeconds: number;
  assessmentStaleAfterSeconds: number;
}) {
  const detailed = vehicles.length === 1;

  return (
    <section id="fleet" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-ink">
            {detailed ? "Vehicle" : "Fleet"}
          </h2>
          <p className="mt-0.5 text-xs text-ink-subtle">
            {vehicles.length} vehicle{vehicles.length === 1 ? "" : "s"}. Telemetry is
            fresh within {Math.round(telemetryStaleAfterSeconds)}s; an assessment is
            current within {Math.round(assessmentStaleAfterSeconds)}s of the monitor cycle.
          </p>
        </div>
      </div>

      <div
        className={
          detailed
            ? "grid gap-4"
            : "grid gap-4 md:grid-cols-2 xl:grid-cols-3"
        }
      >
        {vehicles.map((vehicle) => (
          <FleetVehicleCard key={vehicle.vehicle_id} row={vehicle} detailed={detailed} />
        ))}
      </div>
    </section>
  );
}

export function FleetVehicleCard({
  row,
  detailed = false,
}: {
  row: FleetVehicleSummary;
  detailed?: boolean;
}) {
  const simulator = SIMULATOR_STATE[row.simulation_state];
  const telemetry = TELEMETRY_FRESHNESS[row.telemetry_freshness];
  const reason = attentionReason(row);

  return (
    <Card className="flex flex-col gap-3 p-4" data-testid={`fleet-vehicle-${row.vehicle_id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-ink">
            {row.make} {row.model}
          </h3>
          <p className="mt-0.5 truncate text-xs text-ink-subtle">
            {row.year}
            {row.engine_type ? ` · ${row.engine_type}` : ""} ·{" "}
            <span className="font-mono" title={row.vin}>
              {maskVin(row.vin)}
            </span>
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge tone={simulator.tone} size="sm">
            <CirclePlay className="size-3" aria-hidden />
            {simulator.label}
          </Badge>
          {row.requires_attention ? (
            <Badge tone="attention" size="sm">
              <TriangleAlert className="size-3" aria-hidden />
              Needs attention
            </Badge>
          ) : null}
        </div>
      </div>

      {detailed ? <AssessmentBlock row={row} showRing /> : null}

      <dl
        className={
          detailed
            ? "grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4"
            : "grid grid-cols-2 gap-x-4 gap-y-2 text-xs"
        }
      >
        <div>
          <dt className="text-ink-subtle">Telemetry</dt>
          <dd className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <Badge tone={telemetry.tone} size="sm">
              {telemetry.label}
            </Badge>
            <span className="text-ink-muted">{formatRelative(row.last_telemetry_at)}</span>
          </dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Assessment</dt>
          <dd className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <AssessmentInline row={row} />
          </dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Alerts</dt>
          <dd className="mt-0.5">
            <AlertsInline row={row} />
          </dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Scenario</dt>
          <dd className="mt-0.5 text-ink-muted">
            {row.simulation_scenario ? titleCase(row.simulation_scenario) : "—"}
          </dd>
        </div>
      </dl>

      {reason ? (
        <p className="text-[0.7rem] text-[color:var(--color-attention)]">{reason}.</p>
      ) : null}

      {(row.simulation_state === "degraded" || row.simulation_state === "error") &&
      row.simulation_error ? (
        <InlineAlert tone={row.simulation_state === "error" ? "critical" : "attention"}>
          {row.simulation_error}
        </InlineAlert>
      ) : null}

      <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <Button asChild size="sm">
          <Link href={`/vehicles/${row.vehicle_id}`}>
            Open workspace
            <ArrowRight aria-hidden />
          </Link>
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link href={`/vehicles/${row.vehicle_id}/alerts`}>
            <BellRing aria-hidden />
            Alerts
            {row.open_alerts > 0 ? ` (${row.open_alerts})` : ""}
          </Link>
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link href={`/vehicles/${row.vehicle_id}/simulation`}>
            <CirclePlay aria-hidden />
            Simulation
          </Link>
        </Button>
      </div>
    </Card>
  );
}

function AssessmentInline({ row }: { row: FleetVehicleSummary }) {
  const freshness = ASSESSMENT_FRESHNESS[row.assessment_freshness];
  if (!row.assessment) {
    return <span className="text-ink-subtle">Not assessed</span>;
  }
  const rating = assessmentRating(row.assessment);
  return (
    <>
      <HealthStatusBadge status={rating} size="sm" />
      {row.assessment.provisional ? (
        <Badge tone="unknown" size="sm">
          Provisional
        </Badge>
      ) : null}
      <span className="text-ink-muted">{formatRelative(row.assessment.generated_at)}</span>
      {row.assessment_freshness !== "fresh" ? (
        <Badge tone={freshness.tone} size="sm">
          {freshness.label}
        </Badge>
      ) : null}
    </>
  );
}

function AlertsInline({ row }: { row: FleetVehicleSummary }) {
  if (row.open_alerts === 0) {
    return <span className="text-ink-subtle">None</span>;
  }
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {row.critical_open_alerts > 0 ? (
        <Badge tone="critical" size="sm">
          {row.critical_open_alerts} critical
        </Badge>
      ) : null}
      {row.warning_open_alerts > 0 ? (
        <Badge tone="attention" size="sm">
          {row.warning_open_alerts} warning
        </Badge>
      ) : null}
    </span>
  );
}

/**
 * A richer, always-qualified view of the stored assessment: its score, its own
 * timestamp, and — for provisional or aged assessments — the caveat that stops
 * it reading as the vehicle's current, definitive state.
 */
function AssessmentBlock({
  row,
  showRing = false,
}: {
  row: FleetVehicleSummary;
  showRing?: boolean;
}) {
  const assessment = row.assessment;
  if (!assessment) {
    return (
      <p className="rounded-md border border-dashed border-line px-3 py-4 text-xs text-ink-subtle">
        No stored health assessment yet. One is produced automatically once the
        vehicle has enough current-session telemetry.
      </p>
    );
  }

  const rating = assessmentRating(assessment);
  const freshness = ASSESSMENT_FRESHNESS[row.assessment_freshness];

  return (
    <div className="flex flex-wrap items-center gap-4">
      {showRing ? (
        <HealthScoreRing score={assessment.health_score} status={rating} size={128} strokeWidth={10} />
      ) : null}
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <HealthStatusBadge status={rating} />
          {assessment.provisional ? (
            <Badge tone="unknown" size="sm">
              Provisional — limited data
            </Badge>
          ) : null}
          <Badge tone={freshness.tone} size="sm">
            {freshness.label}
          </Badge>
        </div>
        <p className="text-xs text-ink-muted" title={assessment.generated_at}>
          Assessed {formatRelative(assessment.generated_at)} ·{" "}
          {formatDateTime(assessment.generated_at)}
        </p>
        <p className="text-[0.7rem] text-ink-subtle">
          {assessmentBlockDetail(assessment, row)}
        </p>
        {row.assessment_freshness !== "fresh" ? (
          <p className="text-[0.7rem] text-[color:var(--color-attention)]">
            {freshness.description}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function assessmentBlockDetail(
  assessment: FleetAssessmentSummary,
  row: FleetVehicleSummary,
): string {
  const parts = [
    `Score ${assessment.health_score === null ? "—" : Math.round(assessment.health_score)}/100`,
    `confidence ${formatPercent(assessment.confidence)}`,
  ];
  if (assessment.sample_count !== null) parts.push(`${assessment.sample_count} samples`);
  if (assessment.data_sufficiency) {
    parts.push(titleCase(assessment.data_sufficiency));
  }
  if (assessment.analysis_scope) parts.push(titleCase(assessment.analysis_scope));
  if (row.last_telemetry_at) {
    parts.push(`newest telemetry ${formatRelative(row.last_telemetry_at)}`);
  }
  return parts.join(" · ");
}

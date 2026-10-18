"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/states/feedback";
import { HealthStatusBadge } from "@/components/health/health-visuals";
import { assessmentRating, attentionReason } from "@/lib/fleet";
import { formatRelative } from "@/lib/format";
import type { FleetVehicleSummary } from "@/types/api";

/**
 * The vehicles that need a human right now.
 *
 * Membership is the backend's `requires_attention` flag: an active
 * warning/critical alert, or a *current* attention/critical assessment. An aged
 * assessment never appears here, so this is a present-tense list, not a history.
 */
export function FleetAttentionPanel({ vehicles }: { vehicles: FleetVehicleSummary[] }) {
  const flagged = vehicles.filter((vehicle) => vehicle.requires_attention);

  return (
    <section id="fleet-attention" className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold tracking-tight text-ink">Needs attention</h2>
        <p className="mt-0.5 text-xs text-ink-subtle">
          Vehicles with an active alert or a current attention/critical assessment.
          Aged assessments are shown in the fleet list, not here.
        </p>
      </div>

      {flagged.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 className="size-5" aria-hidden />}
          title="Nothing needs attention"
          description="No vehicle currently has an active alert or a current attention/critical assessment."
        />
      ) : (
        <div className="space-y-2">
          {flagged.map((row) => (
            <AttentionRow key={row.vehicle_id} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}

function AttentionRow({ row }: { row: FleetVehicleSummary }) {
  const reason = attentionReason(row);
  const rating = assessmentRating(row.assessment);

  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-3.5">
      <div className="flex min-w-0 items-center gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-[color:color-mix(in_oklab,var(--color-attention)_14%,transparent)] text-[color:var(--color-attention)]">
          <TriangleAlert className="size-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">
            {row.make} {row.model}
          </p>
          <p className="truncate text-xs text-ink-subtle">{reason}.</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {row.assessment && rating ? <HealthStatusBadge status={rating} size="sm" /> : null}
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
        {row.assessment ? (
          <span className="text-[0.7rem] text-ink-subtle">
            assessed {formatRelative(row.assessment.generated_at)}
          </span>
        ) : null}
        <Button asChild variant="ghost" size="sm">
          <Link href={`/vehicles/${row.vehicle_id}`}>
            Open
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      </div>
    </Card>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { CirclePlay, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { LiveHealthStatusBody } from "@/components/health/live-health-status";
import { ContextualPipeline } from "@/components/workflow/contextual-pipeline";
import { useLiveHealth } from "@/hooks/use-vehicle-data";

/**
 * Simulation control card for one vehicle: the honest live view of the active
 * run. The simulator state, the run identity, the data-freshness state and,
 * once enough fresh current-run evidence exists, the definitive assessment.
 * A stopped vehicle, a collecting session or a stale feed is shown as-is —
 * never as a historical snapshot dressed up as current.
 */
export function VehicleSimulationView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  const live = useLiveHealth(vehicleId);
  const status = live.data ?? null;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-signal-400">
                <CirclePlay className="size-4" aria-hidden />
              </span>
              <div>
                <CardTitle>Live simulation status</CardTitle>
                <CardDescription>
                  The current simulator run, its data freshness, and the live
                  assessment — refreshed automatically.
                </CardDescription>
              </div>
            </div>
            <Button variant="outline" size="sm" asChild>
              <Link href="/simulations">
                <ExternalLink aria-hidden />
                Simulation control
              </Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {live.isPending && !status ? (
            <div className="space-y-2.5">
              <Skeleton className="h-16 w-full rounded-lg" />
              <Skeleton className="h-24 w-full rounded-lg" />
            </div>
          ) : status ? (
            <LiveHealthStatusBody status={status} />
          ) : null}
        </CardContent>
      </Card>

      <ContextualPipeline id="health" vehicleId={vehicleId} hideWhenEmpty={false} />
    </div>
  );
}

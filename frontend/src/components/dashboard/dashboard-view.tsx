"use client";

import Link from "next/link";
import { Car, PlusCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/page-header";
import { FleetKpis, FleetKpisSkeleton } from "@/components/dashboard/fleet-kpis";
import { PlatformStatus, PlatformStatusSkeleton } from "@/components/dashboard/platform-status";
import { FleetVehicleList } from "@/components/dashboard/fleet-vehicle-list";
import { FleetAttentionPanel } from "@/components/dashboard/fleet-attention";
import {
  useApiLiveness,
  useDatabaseHealth,
  useFleetOverview,
  useWorkflowSystemStatus,
} from "@/hooks/use-fleet";
import { toApiError } from "@/lib/api-error";

/**
 * Fleet-level "Vehicle Intelligence Overview".
 *
 * Unlike the per-vehicle workspace pages, this page is deliberately *not*
 * centred on any one vehicle: it reports the state of every vehicle the caller
 * can access. All classifications (telemetry freshness, attention, alert
 * counts) come from the backend snapshot; the page never derives or fabricates
 * them. Availability signals are independent and a probe that cannot be read is
 * shown as "Unknown".
 */
export function DashboardView() {
  const overview = useFleetOverview();
  const liveness = useApiLiveness();
  const database = useDatabaseHealth();
  const workflow = useWorkflowSystemStatus();

  const data = overview.data;
  const isFirstLoad = overview.isPending && !data;

  const refreshAll = () => {
    void overview.refetch();
    void liveness.refetch();
    void database.refetch();
    void workflow.refetch();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Vehicle intelligence overview"
        description="A fleet-level view of what is actually being measured across your vehicles. Deterministic rule assessments and stored telemetry only — no simulated or predicted values."
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={refreshAll}
              loading={overview.isFetching}
            >
              <RefreshCw aria-hidden />
              Refresh
            </Button>
            <Button asChild size="sm">
              <Link href="/vehicles">
                <PlusCircle aria-hidden />
                Register vehicle
              </Link>
            </Button>
          </>
        }
      />

      {/* Platform probes are independent of the fleet snapshot, so they render
          even when the fleet request fails. */}
      {overview.isError ? (
        <ErrorState
          error={overview.error}
          onRetry={() => overview.refetch()}
          retryLabel="Retry fleet"
        />
      ) : null}

      {isFirstLoad ? (
        <DashboardSkeleton />
      ) : (
        <>
          {overview.isError && data ? (
            <InlineAlert tone="attention" title="Showing the last fleet snapshot">
              The latest refresh failed ({toApiError(overview.error).message}). The
              values below are the most recent successful read.
            </InlineAlert>
          ) : null}

          {data ? (
            <PlatformStatus
              liveness={liveness}
              database={database}
              workflow={workflow}
              totals={data.totals}
              generatedAt={data.generated_at}
            />
          ) : (
            <PlatformStatus
              liveness={liveness}
              database={database}
              workflow={workflow}
              totals={null}
              generatedAt={null}
            />
          )}

          {data ? (
            <>
              <FleetKpis totals={data.totals} />

              {data.vehicles.length === 0 ? (
                <EmptyState
                  icon={<Car className="size-5" aria-hidden />}
                  title="No vehicles yet"
                  description="Register a vehicle with its VIN. Once telemetry arrives from the MQTT pipeline, the deterministic rule engine scores it automatically and this overview fills in."
                  action={
                    <Button asChild size="sm">
                      <Link href="/vehicles">
                        <PlusCircle aria-hidden />
                        Register a vehicle
                      </Link>
                    </Button>
                  }
                />
              ) : (
                <>
                  <FleetAttentionPanel vehicles={data.vehicles} />
                  <FleetVehicleList
                    vehicles={data.vehicles}
                    telemetryStaleAfterSeconds={data.telemetry_stale_after_seconds}
                    assessmentStaleAfterSeconds={data.assessment_stale_after_seconds}
                  />
                </>
              )}
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <PlatformStatusSkeleton />
      <FleetKpisSkeleton />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-52 rounded-xl" />
        ))}
      </div>
      <p className="text-xs text-ink-subtle">Loading the fleet snapshot…</p>
    </div>
  );
}

"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { ArrowLeft, Car } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/states/feedback";
import { useVehicle } from "@/hooks/use-vehicle-data";
import { useVehicleSelection } from "@/stores/vehicle-selection";
import { VEHICLE_TABS } from "@/components/layout/nav-items";
import { cn } from "@/lib/utils";

/**
 * Vehicle workspace chrome: identity block + tab navigation shared by the
 * overview, health, telemetry, diagnosis and history routes.
 */
export function VehicleWorkspace({ children }: { children: React.ReactNode }) {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";
  const pathname = usePathname();
  const router = useRouter();
  const select = useVehicleSelection((state) => state.select);
  const { data: vehicle, isPending, isError, error } = useVehicle(vehicleId);

  // Opening a workspace makes it the active vehicle for the rest of the app.
  React.useEffect(() => {
    if (vehicleId) select(vehicleId);
  }, [vehicleId, select]);

  if (isError) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft aria-hidden />
          Back
        </Button>
        <ErrorState
          error={error}
          onRetry={() => router.refresh()}
        />
        <p className="text-xs text-ink-subtle">
          A 404 or 403 here usually means the vehicle does not exist or belongs to
          another account — the backend refuses both.
        </p>
      </div>
    );
  }

  const base = `/vehicles/${vehicleId}`;

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link href="/vehicles">
            <ArrowLeft aria-hidden />
            All vehicles
          </Link>
        </Button>
      </div>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-line bg-surface text-signal-400">
            <Car className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            {isPending || !vehicle ? (
              <>
                <Skeleton className="h-5 w-52" />
                <Skeleton className="mt-2 h-3 w-72" />
              </>
            ) : (
              <>
                <h1 className="truncate text-lg font-semibold tracking-tight text-ink sm:text-xl">
                  {vehicle.make} {vehicle.model}
                </h1>
                <p className="tabular mt-1 text-xs text-ink-subtle">
                  {vehicle.year} ·{" "}
                  <span className="font-mono text-ink-muted">{vehicle.vin}</span>
                  {vehicle.engine_type ? ` · ${vehicle.engine_type}` : ""} ·{" "}
                  {vehicle.status}
                </p>
              </>
            )}
          </div>
        </div>
      </header>

      <nav aria-label="Vehicle sections" className="border-b border-line">
        <ul className="-mb-px flex gap-1 overflow-x-auto scrollbar-slim">
          {VEHICLE_TABS.map((tab) => {
            const href = `${base}${tab.href}`;
            const active = pathname === href;
            return (
              <li key={tab.href || "overview"}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex whitespace-nowrap border-b-2 px-3 py-2.5 text-xs font-medium transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
                    active
                      ? "border-signal-500 text-ink"
                      : "border-transparent text-ink-subtle hover:text-ink",
                  )}
                >
                  {tab.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div>{children}</div>
    </div>
  );
}

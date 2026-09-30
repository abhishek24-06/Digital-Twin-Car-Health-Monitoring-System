"use client";

import * as React from "react";
import Link from "next/link";
import { SelectMenu } from "@/components/ui/select-menu";
import { useVehicles } from "@/hooks/use-vehicle-data";
import { useVehicleSelection } from "@/stores/vehicle-selection";
import { Car } from "lucide-react";

/**
 * Vehicle selector shown in the top bar. Only vehicles the signed-in user owns
 * are listed (the backend scopes the endpoint), so it can never surface another
 * account's vehicle.
 */
export function VehicleSelector({ compact = false }: { compact?: boolean }) {
  const { data: vehicles, isLoading, isError } = useVehicles();
  const selectedVehicleId = useVehicleSelection((state) => state.selectedVehicleId);
  const select = useVehicleSelection((state) => state.select);

  React.useEffect(() => {
    if (!vehicles || vehicles.length === 0) return;
    if (
      !selectedVehicleId ||
      !vehicles.some((vehicle) => vehicle.id === selectedVehicleId)
    ) {
      select(vehicles[0].id);
    }
  }, [vehicles, selectedVehicleId, select]);

  if (isError) {
    return (
      <p className="px-3 text-xs text-ink-subtle">Vehicles unavailable</p>
    );
  }

  if (isLoading) {
    return (
      <div
        className="h-9 w-48 animate-pulse rounded-md border border-line bg-surface-2"
        aria-hidden
      />
    );
  }

  if (!vehicles || vehicles.length === 0) {
    return (
      <Link
        href="/vehicles"
        className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-xs text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
      >
        <Car className="size-3.5" aria-hidden />
        Add a vehicle
      </Link>
    );
  }

  const options = vehicles.map((vehicle) => ({
    value: vehicle.id,
    label: `${vehicle.make} ${vehicle.model}`,
    description: `${vehicle.year}${vehicle.engine_type ? ` · ${vehicle.engine_type}` : ""}`,
  }));

  return (
    <div className={compact ? "w-full" : "w-[15rem]"}>
      <SelectMenu
        value={selectedVehicleId}
        options={options}
        onChange={select}
        label="Select vehicle"
        placeholder="Select vehicle"
        triggerClassName="h-9 py-0"
      />
    </div>
  );
}

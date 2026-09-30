"use client";

import { useVehicles } from "@/hooks/use-vehicle-data";
import { useVehicleSelection } from "@/stores/vehicle-selection";

/**
 * The vehicle every page should render.
 *
 * Falls back to the first vehicle the backend returns when nothing is selected,
 * so a deep link such as `/dashboard` works on a brand-new account.
 */
export function useActiveVehicleId(): {
  vehicleId: string | null;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  hasVehicles: boolean;
} {
  const { data: vehicles, isPending, isError, error } = useVehicles();
  const selected = useVehicleSelection((state) => state.selectedVehicleId);

  const vehicleId =
    selected && vehicles?.some((vehicle) => vehicle.id === selected)
      ? selected
      : (vehicles?.[0]?.id ?? null);

  return {
    vehicleId,
    isLoading: isPending,
    isError,
    error,
    hasVehicles: (vehicles?.length ?? 0) > 0,
  };
}

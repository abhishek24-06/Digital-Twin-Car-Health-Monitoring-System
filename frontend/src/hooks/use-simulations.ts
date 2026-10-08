"use client";

import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { simulationsApi } from "@/services/simulations";
import type {
  PaginatedResponse,
  SimulationStatusResponse,
} from "@/types/api";

/**
 * Simulation status for every vehicle the signed-in user can access.
 *
 * Polled roughly every 5 seconds so a Start/Restart/Stop takes effect quickly
 * and external changes (a crashed simulator, a stale MQTT feed) surface on
 * their own. `placeholderData` keeps the previous list on screen between
 * refetches instead of flashing a loading state.
 */
export function useSimulations(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.simulations,
    queryFn: ({ signal }) => simulationsApi.list(1, 100, signal),
    select: (data: PaginatedResponse<SimulationStatusResponse>) => data.items,
    enabled: options.enabled ?? true,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    staleTime: 2_000,
    placeholderData: (previous) => previous,
  });
}
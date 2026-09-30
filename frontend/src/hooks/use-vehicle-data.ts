"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-error";
import { queryKeys } from "@/lib/query-keys";
import { agentApi, healthApi, telemetryApi, vehiclesApi } from "@/services/vehicles";
import type {
  DiagnosisResponse,
  HealthContextResponse,
  PaginatedResponse,
  TelemetryResponse,
  VehicleResponse,
} from "@/types/api";

/** Vehicles the signed-in user owns (backend filters by ownership). */
export function useVehicles(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.vehicles,
    queryFn: ({ signal }) => vehiclesApi.list(1, 100, signal),
    select: (data: PaginatedResponse<VehicleResponse>) => data.items,
    enabled: options.enabled ?? true,
    staleTime: 30_000,
  });
}

export function useVehicle(vehicleId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.vehicle(vehicleId ?? "none"),
    queryFn: ({ signal }) => vehiclesApi.get(vehicleId as string, signal),
    enabled: Boolean(vehicleId),
  });
}

/**
 * Latest persisted health context. A 404 means "no snapshot yet" — that is an
 * empty state, not an error, so it is normalised to `null` here.
 */
export function useHealthContext(vehicleId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.health(vehicleId ?? "none"),
    queryFn: async ({ signal }): Promise<HealthContextResponse | null> => {
      try {
        return await healthApi.latest(vehicleId as string, signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: Boolean(vehicleId),
    retry: 1,
  });
}

export interface TelemetryRangeSpec {
  key: string;
  minutes: number;
}

/**
 * Telemetry for a trailing window.
 *
 * The window is computed inside `queryFn` (not during render) so it always
 * reflects "the last N minutes" at request time, which keeps the polling
 * meaningful and keeps render pure.
 */
export function useTelemetryWindow(
  vehicleId: string | null | undefined,
  range: TelemetryRangeSpec | null,
  options: { page?: number; pageSize?: number; enabled?: boolean } = {},
) {
  const { page = 1, pageSize = 100 } = options;
  return useQuery({
    queryKey: queryKeys.telemetry(vehicleId ?? "none", range?.key ?? "none", page),
    queryFn: ({ signal }) => {
      const end = Date.now();
      return telemetryApi.list(
        vehicleId as string,
        {
          page,
          pageSize,
          startTime: new Date(end - (range?.minutes ?? 60) * 60_000).toISOString(),
          endTime: new Date(end).toISOString(),
        },
        signal,
      );
    },
    enabled: Boolean(vehicleId) && Boolean(range) && (options.enabled ?? true),
    // Live-ish: the simulator streams continuously, so poll gently.
    refetchInterval: 20_000,
    refetchIntervalInBackground: false,
    placeholderData: (previous) => previous,
    staleTime: 5_000,
  });
}

/** The newest telemetry sample, derived from the first row (newest first). */
export function latestTelemetry(
  items: TelemetryResponse[] | undefined,
): TelemetryResponse | null {
  return items && items.length > 0 ? items[0] : null;
}

export function useHealthHistory(
  vehicleId: string | null | undefined,
  page = 1,
) {
  return useQuery({
    queryKey: queryKeys.healthHistory(vehicleId ?? "none", page),
    queryFn: ({ signal }) =>
      healthApi.history(vehicleId as string, { page, pageSize: 20 }, signal),
    enabled: Boolean(vehicleId),
  });
}

export function useAgentDashboard(vehicleId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.agentDashboard(vehicleId ?? "none"),
    queryFn: ({ signal }) => agentApi.dashboard(vehicleId as string, signal),
    enabled: Boolean(vehicleId),
  });
}

/** Latest diagnosis; 404 means none yet (empty state, not an error). */
export function useLatestDiagnosis(vehicleId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.agentLatest(vehicleId ?? "none"),
    queryFn: async ({ signal }): Promise<DiagnosisResponse | null> => {
      try {
        return await agentApi.latest(vehicleId as string, signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: Boolean(vehicleId),
    retry: 1,
  });
}

export function useAgentHistory(
  vehicleId: string | null | undefined,
  page = 1,
) {
  return useQuery({
    queryKey: queryKeys.agentHistory(vehicleId ?? "none", page),
    queryFn: ({ signal }) =>
      agentApi.history(vehicleId as string, { page, pageSize: 20 }, signal),
    enabled: Boolean(vehicleId),
  });
}
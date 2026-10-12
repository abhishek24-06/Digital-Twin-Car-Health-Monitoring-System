"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-error";
import { queryKeys } from "@/lib/query-keys";
import {
  agentApi,
  healthApi,
  historicalAnalyticsApi,
  liveHealthApi,
  telemetryApi,
  vehiclesApi,
} from "@/services/vehicles";
import { alertsApi } from "@/services/alerts";
import type {
  AlertDetail,
  AlertItem,
  AlertStatus,
  DiagnosisResponse,
  HealthContextResponse,
  HistoricalAnalyticsResponse,
  HistoricalRangePreset,
  LiveHealthStatusResponse,
  PaginatedResponse,
  Severity,
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

/**
 * Live current-session health. Polls gently while the page is open: the live
 * view reflects the fresh current run (fresh / collecting / stale / no session)
 * plus the definitive assessment once the sufficiency gate clears.
 */
export function useLiveHealth(vehicleId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.liveHealth(vehicleId ?? "none"),
    queryFn: ({ signal }): Promise<LiveHealthStatusResponse> =>
      liveHealthApi.get(vehicleId as string, signal),
    enabled: Boolean(vehicleId),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    staleTime: 5_000,
  });
}

export interface HistoricalAnalyticsQuerySpec {
  range: HistoricalRangePreset;
  timezone: string;
  startTime?: string;
  endTime?: string;
}

/** Read-only historical analytics for one validated window (null spec = disabled). */
export function useHistoricalAnalytics(
  vehicleId: string | null | undefined,
  params: HistoricalAnalyticsQuerySpec | null,
) {
  return useQuery({
    queryKey: queryKeys.historicalAnalytics(
      vehicleId ?? "none",
      params?.range ?? "none",
      params?.timezone ?? "none",
    ),
    queryFn: ({ signal }): Promise<HistoricalAnalyticsResponse> =>
      historicalAnalyticsApi.get(vehicleId as string, params as HistoricalAnalyticsQuerySpec, signal),
    enabled: Boolean(vehicleId) && params !== null,
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

export interface VehicleAlertsSpec {
  status?: AlertStatus;
  severity?: Severity;
  page?: number;
}

/**
 * A vehicle's persistent alerts. Placeholder data keeps the current page
 * visible while a filter/page change is fetching, so the table never flashes
 * empty between requests — but it is scoped to the *same vehicle*, so a vehicle
 * switch can never briefly show another vehicle's alerts.
 */
export function useVehicleAlerts(
  vehicleId: string | null | undefined,
  spec: VehicleAlertsSpec = {},
) {
  const { status, severity, page = 1 } = spec;
  const scope = vehicleId ?? "none";
  return useQuery({
    queryKey: queryKeys.alerts(scope, status ?? "all", severity ?? "all", page),
    queryFn: ({ signal }): Promise<PaginatedResponse<AlertItem>> =>
      alertsApi.list(vehicleId as string, { status, severity, page, pageSize: 20 }, signal),
    enabled: Boolean(vehicleId),
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey?.[1] === scope ? previous : undefined,
  });
}

/** One alert's detail (raw evidence + audit history). Disabled without an id. */
export function useAlertDetail(
  vehicleId: string | null | undefined,
  alertId: string | null | undefined,
) {
  return useQuery({
    queryKey: queryKeys.alert(vehicleId ?? "none", alertId ?? "none"),
    queryFn: ({ signal }): Promise<AlertDetail> =>
      alertsApi.get(vehicleId as string, alertId as string, signal),
    enabled: Boolean(vehicleId) && Boolean(alertId),
  });
}
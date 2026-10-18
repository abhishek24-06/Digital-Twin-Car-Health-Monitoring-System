"use client";

import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { fleetApi, systemApi } from "@/services/fleet";
import { workflowApi } from "@/services/workflow";

/**
 * How often the dashboard re-reads the fleet snapshot. It is kept comfortably
 * under the backend's telemetry stale threshold so a "Live" row can never be
 * more than a few seconds out of date.
 */
const FLEET_POLL_MS = 10_000;
const PLATFORM_POLL_MS = 30_000;

/** The single fleet snapshot: every vehicle plus the KPI totals. */
export function useFleetOverview() {
  return useQuery({
    queryKey: queryKeys.fleetOverview,
    queryFn: ({ signal }) => fleetApi.overview(signal),
    refetchInterval: FLEET_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: 5_000,
    placeholderData: (previous) => previous,
  });
}

/** API liveness only. A failure here means the API process is unreachable. */
export function useApiLiveness() {
  return useQuery({
    queryKey: queryKeys.apiLiveness,
    queryFn: ({ signal }) => systemApi.liveness(signal),
    refetchInterval: PLATFORM_POLL_MS,
    staleTime: 10_000,
  });
}

/** Database reachability only. Kept separate from API liveness on purpose. */
export function useDatabaseHealth() {
  return useQuery({
    queryKey: queryKeys.databaseHealth,
    queryFn: ({ signal }) => systemApi.database(signal),
    refetchInterval: PLATFORM_POLL_MS,
    staleTime: 10_000,
  });
}

/**
 * Pipeline status (subscriber / telemetry flow / active simulations). Kept as
 * its own query so a failure here degrades only the status panel, never the
 * fleet list.
 */
export function useWorkflowSystemStatus() {
  return useQuery({
    queryKey: queryKeys.workflowSystemStatus,
    queryFn: () => workflowApi.getWorkflowStatus(),
    refetchInterval: PLATFORM_POLL_MS,
    staleTime: 10_000,
  });
}

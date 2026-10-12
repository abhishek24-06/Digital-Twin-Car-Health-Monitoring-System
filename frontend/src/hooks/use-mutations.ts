"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { alertsApi } from "@/services/alerts";
import { simulationsApi } from "@/services/simulations";
import { agentApi, healthApi, telemetryApi, vehiclesApi } from "@/services/vehicles";
import { queryKeys } from "@/lib/query-keys";
import type {
  PaginatedResponse,
  SimulationStartRequest,
  SimulationStatusResponse,
} from "@/types/api";

/**
 * Mutations and their invalidation graph.
 *
 * "Analyze Health" invalidates the health context, the health history and the
 * agent dashboard. "Ask AI" invalidates the latest diagnosis, the history and
 * the dashboard. Telemetry submission invalidates the telemetry windows.
 */

export function useAnalyzeHealth(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (windowMinutes?: number) => healthApi.analyze(vehicleId, windowMinutes),
    onSuccess: (context) => {
      queryClient.setQueryData(queryKeys.health(vehicleId), context);
      void queryClient.invalidateQueries({
        queryKey: ["health-history", vehicleId],
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agentDashboard(vehicleId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.health(vehicleId) });
    },
  });
}

export function useAskAgent(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (query: string) => agentApi.ask(vehicleId, query),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentLatest(vehicleId) });
      void queryClient.invalidateQueries({
        queryKey: ["agent-history", vehicleId],
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agentDashboard(vehicleId),
      });
    },
  });
}

export function useCreateVehicle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: vehiclesApi.create,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.vehicles });
    },
  });
}

export function useUpdateVehicle(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof vehiclesApi.update>[1]) =>
      vehiclesApi.update(vehicleId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.vehicles });
      void queryClient.invalidateQueries({ queryKey: queryKeys.vehicle(vehicleId) });
    },
  });
}

export function useDeleteVehicle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vehicleId: string) => vehiclesApi.remove(vehicleId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.vehicles });
    },
  });
}

export function useCreateTelemetry(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof telemetryApi.create>[1]) =>
      telemetryApi.create(vehicleId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["telemetry", vehicleId] });
      void queryClient.invalidateQueries({
        queryKey: ["telemetry-window", vehicleId],
      });
    },
  });
}

/**
 * One optimistic patch of the in-memory simulations list so the polled page
 * shows the mutation's result immediately, before the 5s refetch lands.
 */function patchSimulation(
  queryClient: ReturnType<typeof useQueryClient>,
  status: SimulationStatusResponse | undefined,
) {
  if (!status) return;
  queryClient.setQueryData<PaginatedResponse<SimulationStatusResponse>>(
    queryKeys.simulations,
    (previous) => {
      if (!previous) return previous;
      return {
        ...previous,
        items: previous.items.map((item) =>
          item.vehicle_id === status.vehicle_id ? status : item,
        ),
      };
    },
  );
}

export function useStartSimulation(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SimulationStartRequest) =>
      simulationsApi.start(vehicleId, payload),
    onSuccess: (status) => {
      patchSimulation(queryClient, status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.simulations });
    },
  });
}

export function useRestartSimulation(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SimulationStartRequest) =>
      simulationsApi.restart(vehicleId, payload),
    onSuccess: (status) => {
      patchSimulation(queryClient, status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.simulations });
    },
  });
}

export function useStopSimulation(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => simulationsApi.stop(vehicleId),
    onSuccess: (status) => {
      patchSimulation(queryClient, status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.simulations });
    },
  });
}

export interface AlertActionVariables {
  alertId: string;
  note?: string;
}

/**
 * Acknowledge an alert. The returned detail is written straight into the
 * detail cache and every list page is invalidated so its status badge updates.
 */
export function useAcknowledgeAlert(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, note }: AlertActionVariables) =>
      alertsApi.acknowledge(vehicleId, alertId, note),
    onSuccess: (alert) => {
      queryClient.setQueryData(queryKeys.alert(vehicleId, alert.id), alert);
      void queryClient.invalidateQueries({ queryKey: queryKeys.alertsRoot(vehicleId) });
    },
  });
}

/** Resolve an alert (terminal). A recurrence later creates a new alert. */
export function useResolveAlert(vehicleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, note }: AlertActionVariables) =>
      alertsApi.resolve(vehicleId, alertId, note),
    onSuccess: (alert) => {
      queryClient.setQueryData(queryKeys.alert(vehicleId, alert.id), alert);
      void queryClient.invalidateQueries({ queryKey: queryKeys.alertsRoot(vehicleId) });
    },
  });
}
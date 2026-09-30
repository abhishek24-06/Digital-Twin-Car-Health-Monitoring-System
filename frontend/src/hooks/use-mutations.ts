"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { agentApi, healthApi, telemetryApi, vehiclesApi } from "@/services/vehicles";
import { queryKeys } from "@/lib/query-keys";

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
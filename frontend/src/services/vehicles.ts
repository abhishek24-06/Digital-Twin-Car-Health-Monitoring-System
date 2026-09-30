import { api } from "@/lib/api-client";
import type {
  AgentDiagnosisItem,
  DashboardResponse,
  DiagnosisResponse,
  HealthContextResponse,
  HealthSnapshotItem,
  PaginatedResponse,
  TelemetryCreate,
  TelemetryResponse,
  VehicleCreate,
  VehicleResponse,
  VehicleUpdate,
} from "@/types/api";

/** Vehicle registry — all routes require ownership or admin rights server-side. */
export const vehiclesApi = {
  list: (page = 1, pageSize = 100, signal?: AbortSignal) =>
    api.get<PaginatedResponse<VehicleResponse>>("/vehicles", {
      query: { page, page_size: pageSize },
      ...(signal ? { signal } : {}),
    }),

  get: (vehicleId: string, signal?: AbortSignal) =>
    api.get<VehicleResponse>(`/vehicles/${vehicleId}`, {
      ...(signal ? { signal } : {}),
    }),

  create: (payload: VehicleCreate) =>
    api.post<VehicleResponse>("/vehicles", payload),

  update: (vehicleId: string, payload: VehicleUpdate) =>
    api.patch<VehicleResponse>(`/vehicles/${vehicleId}`, payload),

  remove: (vehicleId: string) => api.delete<void>(`/vehicles/${vehicleId}`),
};

/**
 * Raw telemetry. The frontend never simulates these values — they arrive from
 * the MQTT pipeline in the backend.
 */
export const telemetryApi = {
  list: (
    vehicleId: string,
    params: {
      page?: number;
      pageSize?: number;
      startTime?: string;
      endTime?: string;
    } = {},
    signal?: AbortSignal,
  ) =>
    api.get<PaginatedResponse<TelemetryResponse>>(
      `/vehicles/${vehicleId}/telemetry`,
      {
        query: {
          page: params.page ?? 1,
          page_size: params.pageSize ?? 100,
          start_time: params.startTime,
          end_time: params.endTime,
        },
        ...(signal ? { signal } : {}),
      },
    ),

  /** Advanced/dev-only manual sample submission (kept off the primary UX). */
  create: (vehicleId: string, payload: TelemetryCreate) =>
    api.post<TelemetryResponse>(`/vehicles/${vehicleId}/telemetry`, payload),
};

/** Phase 3 deterministic health analysis. */
export const healthApi = {
  /** 404 means "no snapshot yet", which the UI presents as an empty state. */
  latest: (vehicleId: string, signal?: AbortSignal) =>
    api.get<HealthContextResponse>(`/vehicles/${vehicleId}/health`, {
      ...(signal ? { signal } : {}),
    }),

  analyze: (vehicleId: string, windowMinutes?: number) =>
    api.post<HealthContextResponse>(
      `/vehicles/${vehicleId}/health/analyze`,
      undefined,
      { query: windowMinutes ? { window_minutes: windowMinutes } : {} },
    ),

  history: (
    vehicleId: string,
    params: { page?: number; pageSize?: number } = {},
    signal?: AbortSignal,
  ) =>
    api.get<PaginatedResponse<HealthSnapshotItem>>(
      `/vehicles/${vehicleId}/health/history`,
      {
        query: { page: params.page ?? 1, page_size: params.pageSize ?? 20 },
        ...(signal ? { signal } : {}),
      },
    ),
};

/** Phase 4 reasoning agent. Only `query` and `critical` invoke the LLM. */
export const agentApi = {
  dashboard: (vehicleId: string, signal?: AbortSignal) =>
    api.get<DashboardResponse>(`/vehicles/${vehicleId}/agent/dashboard`, {
      ...(signal ? { signal } : {}),
    }),

  ask: (vehicleId: string, query: string) =>
    api.post<DiagnosisResponse>(`/vehicles/${vehicleId}/agent/query`, { query }),

  criticalEvent: (vehicleId: string, ruleIds?: string[]) =>
    api.post<DiagnosisResponse>(
      `/vehicles/${vehicleId}/agent/events/critical`,
      ruleIds ? { rule_ids: ruleIds } : {},
    ),

  history: (
    vehicleId: string,
    params: { page?: number; pageSize?: number } = {},
    signal?: AbortSignal,
  ) =>
    api.get<PaginatedResponse<AgentDiagnosisItem>>(
      `/vehicles/${vehicleId}/agent/diagnoses`,
      {
        query: { page: params.page ?? 1, page_size: params.pageSize ?? 20 },
        ...(signal ? { signal } : {}),
      },
    ),

  latest: (vehicleId: string, signal?: AbortSignal) =>
    api.get<DiagnosisResponse>(`/vehicles/${vehicleId}/agent/diagnoses/latest`, {
      ...(signal ? { signal } : {}),
    }),
};
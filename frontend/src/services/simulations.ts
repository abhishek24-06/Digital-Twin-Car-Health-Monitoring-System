import { api } from "@/lib/api-client";
import type {
  PaginatedResponse,
  SimulationStartRequest,
  SimulationStatusResponse,
} from "@/types/api";

/**
 * Simulation Control — the backend supervises one `simulator.main` subprocess
 * per vehicle; these calls tell it what to run and read the live state back.
 * Ownership/admin checks happen server-side, exactly like telemetry.
 */
export const simulationsApi = {
  /** Status for every vehicle the caller can access (polled by the UI). */
  list: (page = 1, pageSize = 100, signal?: AbortSignal) =>
    api.get<PaginatedResponse<SimulationStatusResponse>>("/simulations", {
      query: { page, page_size: pageSize },
      ...(signal ? { signal } : {}),
    }),

  status: (vehicleId: string, signal?: AbortSignal) =>
    api.get<SimulationStatusResponse>(`/vehicles/${vehicleId}/simulation`, {
      ...(signal ? { signal } : {}),
    }),

  /** 409 when a simulation is already active for the vehicle. */
  start: (vehicleId: string, payload: SimulationStartRequest) =>
    api.post<SimulationStatusResponse>(`/vehicles/${vehicleId}/simulation`, payload),

  /** Idempotent; a vehicle with no simulator stops as a no-op. */
  stop: (vehicleId: string) =>
    api.delete<SimulationStatusResponse>(`/vehicles/${vehicleId}/simulation`),

  /** Stop any active simulator and start a fresh run with the supplied config. */
  restart: (vehicleId: string, payload: SimulationStartRequest) =>
    api.post<SimulationStatusResponse>(
      `/vehicles/${vehicleId}/simulation/restart`,
      payload,
    ),
};
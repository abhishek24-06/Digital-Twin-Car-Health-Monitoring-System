import { api } from "@/lib/api-client";
import type {
  FleetOverviewResponse,
  HealthDbResponse,
  HealthResponse,
} from "@/types/api";

/**
 * Fleet-level read models. The overview is the single request the dashboard
 * needs for its per-vehicle rows and KPI totals; there is deliberately no
 * per-vehicle fan-out here.
 */
export const fleetApi = {
  overview: (signal?: AbortSignal) =>
    api.get<FleetOverviewResponse>("/fleet/overview", {
      ...(signal ? { signal } : {}),
    }),
};

/**
 * Platform probes. These mirror the backend's own liveness/database checks and
 * are unauthenticated, so the dashboard can distinguish "API unreachable" from
 * "database unreachable" instead of assuming either.
 */
export const systemApi = {
  /** Liveness: does the API process answer at all? Does not touch the DB. */
  liveness: (signal?: AbortSignal) =>
    api.get<HealthResponse>("/health", {
      auth: false,
      ...(signal ? { signal } : {}),
    }),

  /**
   * Database reachability. The backend answers 503 (an error here) when the
   * database is down, so an error state is rendered as "Unavailable".
   */
  database: (signal?: AbortSignal) =>
    api.get<HealthDbResponse>("/health/db", {
      auth: false,
      ...(signal ? { signal } : {}),
    }),
};

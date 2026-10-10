import { api } from "@/lib/api-client";
import type {
  WorkflowRecentResponse,
  WorkflowStateResponse,
  WorkflowStatusResponse,
  WorkflowEventFilters,
} from "@/types/api";

/** Workflow observability API client. */
export const workflowApi = {
  /**
   * Fetch recent workflow events with optional filtering and pagination.
   */
  getRecentEvents: (filters?: WorkflowEventFilters) =>
    api.get<WorkflowRecentResponse>("/workflow/events/recent", {
      query: filters ? (filters as unknown as Record<string, string | number | boolean | null | undefined>) : undefined,
    }),

  /**
   * Get high-level workflow system status.
   */
  getWorkflowStatus: () =>
    api.get<WorkflowStatusResponse>("/workflow/status"),

  /**
   * Read-only derived telemetry pipeline state for one or all accessible
   * vehicles. Backend-enforced: a non-admin never sees another user's vehicle.
   */
  getState: (params?: { vehicle_id?: string }) =>
    api.get<WorkflowStateResponse>("/workflow/state", { query: params }),
};

/**
 * Create an EventSource for live workflow events using the Next.js API proxy.
 * The proxy reads the auth cookie and forwards the SSE stream.
 */
export function createWorkflowEventSource(filters?: {
  workflow?: string;
  status?: string;
  vehicle_id?: string;
  document_id?: string;
  correlation_id?: string;
}): EventSource {
  const params = new URLSearchParams();
  if (filters?.workflow) params.set("workflow", filters.workflow);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.vehicle_id) params.set("vehicle_id", filters.vehicle_id);
  if (filters?.document_id) params.set("document_id", filters.document_id);
  if (filters?.correlation_id) params.set("correlation_id", filters.correlation_id);

  const path = `/api/workflow/events/stream${params.toString() ? `?${params.toString()}` : ""}`;
  return new EventSource(path);
}
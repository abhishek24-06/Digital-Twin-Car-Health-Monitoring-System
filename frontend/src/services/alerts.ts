import { api } from "@/lib/api-client";
import type {
  AlertActionRequest,
  AlertDetail,
  AlertItem,
  AlertStatus,
  PaginatedResponse,
  Severity,
} from "@/types/api";

/**
 * Persistent alerts (Phase 3 backend contract).
 *
 * Alerts are vehicle-scoped; the backend enforces ownership below the router,
 * so an alert or vehicle the caller cannot access is a 404, never a leak. The
 * list view omits raw evidence; the detail view returns it with the full audit
 * history.
 */
export const alertsApi = {
  list: (
    vehicleId: string,
    params: {
      status?: AlertStatus;
      severity?: Severity;
      page?: number;
      pageSize?: number;
    } = {},
    signal?: AbortSignal,
  ) =>
    api.get<PaginatedResponse<AlertItem>>(`/vehicles/${vehicleId}/alerts`, {
      query: {
        status: params.status,
        severity: params.severity,
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
      },
      ...(signal ? { signal } : {}),
    }),

  get: (vehicleId: string, alertId: string, signal?: AbortSignal) =>
    api.get<AlertDetail>(`/vehicles/${vehicleId}/alerts/${alertId}`, {
      ...(signal ? { signal } : {}),
    }),

  acknowledge: (vehicleId: string, alertId: string, note?: string) =>
    api.post<AlertDetail>(
      `/vehicles/${vehicleId}/alerts/${alertId}/acknowledge`,
      body(note),
    ),

  resolve: (vehicleId: string, alertId: string, note?: string) =>
    api.post<AlertDetail>(
      `/vehicles/${vehicleId}/alerts/${alertId}/resolve`,
      body(note),
    ),
};

/** Always send an object; omit `note` when blank so the API stores no note. */
function body(note?: string): AlertActionRequest {
  const trimmed = note?.trim();
  return trimmed ? { note: trimmed } : {};
}

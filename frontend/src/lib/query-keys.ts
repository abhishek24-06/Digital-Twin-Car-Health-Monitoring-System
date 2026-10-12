/**
 * Query keys, centralised so invalidation after a mutation can never drift
 * from the key a component reads.
 */
export const queryKeys = {
  vehicles: ["vehicles"] as const,
  vehicle: (vehicleId: string) => ["vehicles", vehicleId] as const,

  simulations: ["simulations"] as const,

  telemetry: (vehicleId: string, rangeKey: string, page: number) =>
    ["telemetry", vehicleId, rangeKey, page] as const,
  telemetryWindow: (vehicleId: string, rangeKey: string) =>
    ["telemetry-window", vehicleId, rangeKey] as const,

  health: (vehicleId: string) => ["health", vehicleId] as const,
  healthHistory: (vehicleId: string, page: number) =>
    ["health-history", vehicleId, page] as const,
  liveHealth: (vehicleId: string) => ["live-health", vehicleId] as const,
  historicalAnalytics: (vehicleId: string, range: string, timezone: string) =>
    ["historical-analytics", vehicleId, range, timezone] as const,

  agentDashboard: (vehicleId: string) => ["agent-dashboard", vehicleId] as const,
  agentLatest: (vehicleId: string) => ["agent-latest", vehicleId] as const,
  agentHistory: (vehicleId: string, page: number) =>
    ["agent-history", vehicleId, page] as const,

  /**
   * Persistent alerts. `alertsRoot` is the prefix used to invalidate every
   * page/filter at once after a lifecycle mutation.
   */
  alertsRoot: (vehicleId: string) => ["alerts", vehicleId] as const,
  alerts: (vehicleId: string, status: string, severity: string, page: number) =>
    ["alerts", vehicleId, status, severity, page] as const,
  alert: (vehicleId: string, alertId: string) =>
    ["alerts", vehicleId, "detail", alertId] as const,

  ragSearch: (vehicleId: string | null, query: string) =>
    ["rag-search", vehicleId, query] as const,
  ragHealth: ["rag-health"] as const,
  ragDocuments: ["rag-documents"] as const,
  ragDocument: (documentId: string) => ["rag-documents", documentId] as const,
};
/**
 * Query keys, centralised so invalidation after a mutation can never drift
 * from the key a component reads.
 */
export const queryKeys = {
  vehicles: ["vehicles"] as const,
  vehicle: (vehicleId: string) => ["vehicles", vehicleId] as const,

  telemetry: (vehicleId: string, rangeKey: string, page: number) =>
    ["telemetry", vehicleId, rangeKey, page] as const,
  telemetryWindow: (vehicleId: string, rangeKey: string) =>
    ["telemetry-window", vehicleId, rangeKey] as const,

  health: (vehicleId: string) => ["health", vehicleId] as const,
  healthHistory: (vehicleId: string, page: number) =>
    ["health-history", vehicleId, page] as const,

  agentDashboard: (vehicleId: string) => ["agent-dashboard", vehicleId] as const,
  agentLatest: (vehicleId: string) => ["agent-latest", vehicleId] as const,
  agentHistory: (vehicleId: string, page: number) =>
    ["agent-history", vehicleId, page] as const,

  ragSearch: (vehicleId: string | null, query: string) =>
    ["rag-search", vehicleId, query] as const,
  ragHealth: ["rag-health"] as const,
  ragDocuments: ["rag-documents"] as const,
  ragDocument: (documentId: string) => ["rag-documents", documentId] as const,
};
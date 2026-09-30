import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";

/**
 * Shared render helper.
 *
 * Queries are retried off by default in tests, and errors are not logged to the
 * console so a deliberately failing query does not produce noise.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: React.ReactElement,
  options?: RenderOptions & { queryClient?: QueryClient },
) {
  const queryClient = options?.queryClient ?? createTestQueryClient();
  const result = render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
    ...options,
  });
  return { ...result, queryClient };
}

/** Minimal valid user payload for tests. */
export const TEST_USER = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "driver@example.com",
  full_name: "Alex Driver",
  role: "user" as const,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

export const TEST_VEHICLE = {
  id: "22222222-2222-4222-8222-222222222222",
  vin: "1HGCM82633A004352",
  make: "Honda",
  model: "Civic",
  year: 2019,
  engine_type: "1.5L Turbo",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  owner_user_id: TEST_USER.id,
  source_type: "manual",
  status: "active",
  simulation_enabled: false,
};

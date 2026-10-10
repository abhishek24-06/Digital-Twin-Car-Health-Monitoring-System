import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, type RenderOptions } from "@testing-library/react";
import {
  WorkflowStreamProvider,
  type WorkflowEventSourceFactory,
  type WorkflowEventSourceLike,
} from "@/components/workflow/workflow-stream-provider";
import type { WorkflowEventResponse } from "@/types/api";

/**
 * Shared render helper.
 *
 * Queries are retried off by default in tests, and errors are not logged to the
 * console so a deliberately failing query does not produce noise. Every render
 * is wrapped in the shared workflow stream provider so components that consume
 * the workflow slices have a store; tests inject a fake source when they need
 * to drive events.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

/** A manually-driven `EventSource` stand-in for tests. */
export class FakeWorkflowEventSource implements WorkflowEventSourceLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = 0;

  close(): void {
    this.closed += 1;
  }

  open(): void {
    act(() => {
      this.onopen?.(new Event("open"));
    });
  }

  emit(event: WorkflowEventResponse): void {
    act(() => {
      this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    });
  }

  fail(): void {
    act(() => {
      this.onerror?.(new Event("error"));
    });
  }
}

export interface WorkflowStreamHarness {
  factory: WorkflowEventSourceFactory;
  sources: FakeWorkflowEventSource[];
  latest: () => FakeWorkflowEventSource;
}

export function createWorkflowStreamHarness(): WorkflowStreamHarness {
  const sources: FakeWorkflowEventSource[] = [];
  const factory: WorkflowEventSourceFactory = () => {
    const source = new FakeWorkflowEventSource();
    sources.push(source);
    return source;
  };
  return { factory, sources, latest: () => sources[sources.length - 1] };
}

const noopEventSourceFactory: WorkflowEventSourceFactory = () =>
  new FakeWorkflowEventSource();

export interface RenderWithProvidersOptions extends RenderOptions {
  queryClient?: QueryClient;
  eventSourceFactory?: WorkflowEventSourceFactory;
  reconnectDelays?: readonly number[];
}

export function renderWithProviders(
  ui: React.ReactElement,
  options?: RenderWithProvidersOptions,
) {
  const {
    queryClient,
    eventSourceFactory,
    reconnectDelays = [],
    ...renderOptions
  } = options ?? {};
  const client = queryClient ?? createTestQueryClient();
  const result = render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>
        <WorkflowStreamProvider
          eventSourceFactory={eventSourceFactory ?? noopEventSourceFactory}
          reconnectDelays={reconnectDelays}
        >
          {children}
        </WorkflowStreamProvider>
      </QueryClientProvider>
    ),
    ...renderOptions,
  });
  return { ...result, queryClient: client };
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

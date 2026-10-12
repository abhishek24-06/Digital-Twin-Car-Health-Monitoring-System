import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import AppLayout from "@/app/(app)/layout";
import { ContextualPipeline } from "@/components/workflow/contextual-pipeline";
import {
  useWorkflowConnection,
  useWorkflowSlice,
} from "@/components/workflow/workflow-stream-provider";
import { useSessionStore } from "@/lib/session-store";
import { createWorkflowEventSource } from "@/services/workflow";
import { vehiclesApi } from "@/services/vehicles";
import { ThemeProvider } from "@/stores/theme-provider";
import {
  createTestQueryClient,
  createWorkflowStreamHarness,
  TEST_USER,
  TEST_VEHICLE,
} from "@/test/utils";
import type { WorkflowEventResponse } from "@/types/api";

/**
 * Regression: the shared workflow stream must live at the `(app)` layout
 * boundary, not inside the auth-conditional `AppShell`.
 *
 * Previously `AppShell` wrapped its children in `WorkflowStreamProvider` only
 * while `status === "authenticated"`. A 401-triggered `setAnonymous()` (e.g.
 * while asking the agent a question) re-rendered the shell with the page
 * children — including the diagnosis page's `ContextualPipeline` — *outside*
 * the provider, and `useWorkflowConnection()` threw
 * "must be used within a WorkflowStreamProvider".
 */
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/vehicles/v1/diagnosis",
  useParams: () => ({ id: TEST_VEHICLE.id }),
}));

vi.mock("@/services/workflow", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/workflow")>()),
  createWorkflowEventSource: vi.fn(),
}));

vi.mock("@/services/vehicles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/vehicles")>();
  return {
    ...actual,
    vehiclesApi: { ...actual.vehiclesApi, list: vi.fn() },
  };
});

/** Scoped consumer that reports the connection and the agent event count. */
function WorkflowProbe() {
  const connection = useWorkflowConnection();
  const { events } = useWorkflowSlice({ workflow: "agent" });
  return (
    <div>
      <span data-testid="probe-connection">{connection}</span>
      <span data-testid="probe-count">{events.length}</span>
    </div>
  );
}

function agentEvent(
  overrides: Partial<WorkflowEventResponse> = {},
): WorkflowEventResponse {
  return {
    event_id: "agent-evt",
    timestamp: "2026-01-01T00:00:00Z",
    workflow: "agent",
    stage: "reasoning_started",
    status: "running",
    message: "Reasoning",
    vehicle_id: TEST_VEHICLE.id,
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

describe("(app) layout workflow provider boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(vehiclesApi.list).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 100,
      total: 0,
    });
    // Authenticated seed so AppShell renders the full shell, not the skeleton.
    useSessionStore.getState().setSession({
      access_token: "test-token",
      expires_at: null,
      user: TEST_USER,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useSessionStore.setState({ status: "loading" });
  });

  function renderAppLayout() {
    const harness = createWorkflowStreamHarness();
    vi.mocked(createWorkflowEventSource).mockImplementation(
      harness.factory as unknown as typeof createWorkflowEventSource,
    );
    const utils = render(
      <QueryClientProvider client={createTestQueryClient()}>
        <ThemeProvider>
          <AppLayout>
            <ContextualPipeline
              id="agent"
              vehicleId={TEST_VEHICLE.id}
              hideWhenEmpty={false}
            />
            <WorkflowProbe />
          </AppLayout>
        </ThemeProvider>
      </QueryClientProvider>,
    );
    return { ...utils, harness };
  }

  it("renders the diagnosis pipeline inside the provider and survives the auth-state transition that crashed it", async () => {
    const { harness } = renderAppLayout();

    // The pipeline mounted under the shared provider: no missing-provider throw.
    expect(screen.getByText("Agent Pipeline")).toBeTruthy();
    expect(screen.getByText("Connecting")).toBeTruthy();

    // Stream opens -> honest "live" connection.
    harness.latest().open();
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.getByTestId("probe-connection").textContent).toBe("live");

    // Real agent activity drives the pipeline stages.
    harness
      .latest()
      .emit(agentEvent({ event_id: "a", stage: "reasoning_started" }));
    harness
      .latest()
      .emit(
        agentEvent({ event_id: "b", stage: "agent_completed", status: "success" }),
      );
    expect(await screen.findByText("Success")).toBeTruthy();
    expect(screen.getByTestId("probe-count").textContent).toBe("2");

    // Reproduction of the original crash: a 401-triggered setAnonymous() makes
    // the shell re-render without conditional provider mounting. The page
    // children must still be inside the provider, so nothing throws and the
    // connection is not silently dropped.
    act(() => {
      useSessionStore.getState().setAnonymous();
    });

    expect(screen.getByText("Agent Pipeline")).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.getByTestId("probe-connection").textContent).toBe("live");

    // The shared stream keeps delivering after the transition.
    act(() => {
      harness
        .latest()
        .emit(
          agentEvent({
            event_id: "c",
            stage: "agent_completed",
            status: "success",
            message: "Completed",
          }),
        );
    });
    expect(screen.getByTestId("probe-count").textContent).toBe("3");
    expect(screen.getByText("Success")).toBeTruthy();
  });

  it("opens exactly one EventSource for the whole authenticated area", () => {
    const { harness } = renderAppLayout();
    expect(harness.sources).toHaveLength(1);

    // Still one source after the provider survives a shell re-render.
    act(() => {
      useSessionStore.getState().setAnonymous();
    });
    expect(harness.sources).toHaveLength(1);
  });
});
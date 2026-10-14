import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Filters } from "@/components/workflow/filters";
import type { WorkflowEventFilters, WorkflowEventResponse } from "@/types/api";

function event(overrides: Partial<WorkflowEventResponse> = {}): WorkflowEventResponse {
  return {
    event_id: "e1",
    timestamp: new Date().toISOString(),
    workflow: "telemetry",
    stage: "telemetry_persisted",
    status: "success",
    message: "Telemetry persisted",
    vehicle_id: "11111111-1111-4111-8111-111111111111",
    document_id: "22222222-2222-4222-8222-222222222222",
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

const EVENTS: WorkflowEventResponse[] = [
  event({ event_id: "1", workflow: "telemetry", status: "success" }),
  event({ event_id: "2", workflow: "rag_query", status: "error" }),
];

function setup(filters: WorkflowEventFilters = { limit: 100, offset: 0 }) {
  const onFilterChange = vi.fn();
  const onClear = vi.fn();
  render(
    <Filters
      events={EVENTS}
      filters={filters}
      onFilterChange={onFilterChange}
      onClear={onClear}
    />,
  );
  return { onFilterChange, onClear };
}

const workflowTrigger = () =>
  screen.getByRole("button", { name: /filter by workflow/i });
const statusTrigger = () =>
  screen.getByRole("button", { name: /filter by status/i });

describe("Workflow Monitor filter dropdowns", () => {
  it("keeps only one menu open at a time so menus cannot overlap", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(workflowTrigger());
    expect(screen.getByRole("button", { name: "All workflows" })).toBeTruthy();

    await user.click(statusTrigger());
    // Opening the second control closes the first.
    expect(screen.queryByRole("button", { name: "All workflows" })).toBeNull();
    expect(screen.getByRole("button", { name: "All statuses" })).toBeTruthy();
  });

  it("toggles its own menu closed when the trigger is clicked again", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(workflowTrigger());
    expect(screen.getByRole("button", { name: "All workflows" })).toBeTruthy();

    await user.click(workflowTrigger());
    expect(screen.queryByRole("button", { name: "All workflows" })).toBeNull();
  });

  it("closes the menu on Escape", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(workflowTrigger());
    expect(screen.getByRole("button", { name: "All workflows" })).toBeTruthy();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "All workflows" })).toBeNull();
    expect(workflowTrigger().getAttribute("aria-expanded")).toBe("false");
  });

  it("closes the menu on an outside click", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(workflowTrigger());
    expect(screen.getByRole("button", { name: "All workflows" })).toBeTruthy();

    await user.click(document.body);
    expect(screen.queryByRole("button", { name: "All workflows" })).toBeNull();
  });

  it("applies a selection and closes the menu", async () => {
    const user = userEvent.setup();
    const { onFilterChange } = setup();

    await user.click(workflowTrigger());
    await user.click(screen.getByRole("button", { name: "rag_query" }));

    expect(onFilterChange).toHaveBeenCalledWith({
      limit: 100,
      offset: 0,
      workflow: "rag_query",
    });
    expect(screen.queryByRole("button", { name: "rag_query" })).toBeNull();
  });

  it("resets the filter when the placeholder option is chosen", async () => {
    const user = userEvent.setup();
    const { onFilterChange } = setup({ limit: 100, offset: 0, workflow: "telemetry" });

    await user.click(workflowTrigger());
    await user.click(screen.getByRole("button", { name: "All workflows" }));

    const applied = onFilterChange.mock.calls[0][0] as WorkflowEventFilters;
    expect(applied.limit).toBe(100);
    expect(applied.workflow).toBeUndefined();
    expect(screen.queryByRole("button", { name: "All workflows" })).toBeNull();
  });

  it("renders each open menu beneath its own trigger with bounded, scrollable, elevated styling", async () => {
    const user = userEvent.setup();
    setup();

    const trigger = workflowTrigger();
    await user.click(trigger);

    const menu = document.getElementById(trigger.getAttribute("aria-controls")!);
    expect(menu).not.toBeNull();
    const classes = menu!.className;
    // Positioning + stacking.
    expect(classes).toContain("absolute");
    expect(classes).toContain("top-full");
    expect(classes).toContain("left-0");
    expect(classes).toContain("z-20");
    // Bounded height with internal scrolling.
    expect(classes).toContain("max-h-72");
    expect(classes).toContain("overflow-y-auto");
    // Visible surface for the menu.
    expect(classes).toContain("bg-surface");
    expect(classes).toContain("border-line");
  });
});

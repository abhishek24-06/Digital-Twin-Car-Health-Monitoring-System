import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  WORKFLOW_STATUS_META,
  WorkflowStatusBadge,
  type StageStatus,
} from "@/components/workflow/status";

const ALL_STATUSES: StageStatus[] = [
  "started",
  "running",
  "success",
  "warning",
  "degraded",
  "skipped",
  "error",
  "waiting",
];

describe("WorkflowStatusBadge", () => {
  it("renders a label and an accessible name for every status", () => {
    for (const status of ALL_STATUSES) {
      const { unmount } = render(<WorkflowStatusBadge status={status} />);
      const meta = WORKFLOW_STATUS_META[status];
      expect(screen.getByText(meta.label)).toBeInTheDocument();
      expect(screen.getByLabelText(meta.aria)).toBeInTheDocument();
      unmount();
    }
  });

  it("renders 'Degraded' for degraded", () => {
    render(<WorkflowStatusBadge status="degraded" />);
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByLabelText("Degraded")).toBeInTheDocument();
  });

  it("renders 'Skipped' for skipped", () => {
    render(<WorkflowStatusBadge status="skipped" />);
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByLabelText("Skipped")).toBeInTheDocument();
  });

  it("never relies on colour alone (icon + text present)", () => {
    render(<WorkflowStatusBadge status="waiting" />);
    const badge = screen.getByLabelText("Waiting");
    expect(badge.querySelector("svg")).not.toBeNull();
    expect(badge.textContent).toContain("Waiting");
  });
});

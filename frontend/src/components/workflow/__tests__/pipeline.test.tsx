import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  WorkflowConnectionIndicator,
  WorkflowPipeline,
  WorkflowPipelineStep,
} from "@/components/workflow/pipeline";

describe("WorkflowPipeline", () => {
  it("renders each step as a list item without a wrapping card", () => {
    render(
      <WorkflowPipeline
        title="Telemetry Pipeline"
        steps={[
          <WorkflowPipelineStep key="a" label="Simulator" status="waiting" />,
          <WorkflowPipelineStep key="b" label="Broker" status="success" detail="Flow observed" />,
        ]}
      />,
    );

    expect(screen.getByText("Telemetry Pipeline")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Simulator")).toBeInTheDocument();
    expect(screen.getByText("Flow observed")).toBeInTheDocument();
  });

  it("uses a responsive grid for horizontal pipelines", () => {
    render(
      <WorkflowPipeline
        steps={[<WorkflowPipelineStep key="a" label="A" status="waiting" />]}
        orientation="horizontal"
      />,
    );
    const list = screen.getByRole("list");
    expect(list).toHaveClass("grid");
    expect(list).toHaveClass("grid-cols-1");
    expect(list).toHaveClass("sm:grid-cols-2");
    // Four columns only where the viewport (and therefore the card) is wide
    // enough for four readable columns.
    expect(list).toHaveClass("xl:grid-cols-4");
    expect(list).not.toHaveClass("lg:grid-cols-4");
    expect(list).not.toHaveClass("md:flex-row");
  });

  it("keeps the status badge in its own region, not overlapping the title", () => {
    const { container } = render(
      <WorkflowPipeline
        steps={[
          <WorkflowPipelineStep
            key="a"
            position={4}
            label="MQTT Subscriber"
            status="degraded"
          />,
        ]}
      />,
    );
    const item = container.querySelector("li");
    expect(item).not.toBeNull();
    expect(item).toHaveClass("min-w-0");

    const label = screen.getByText("MQTT Subscriber");
    const badge = screen.getByLabelText("Degraded");
    // Badge lives in a different row from the title so it can never overlap.
    expect(label.parentElement).not.toBe(badge.parentElement);
    // It is in normal flow and the title is allowed to wrap long words.
    expect(badge.className).not.toMatch(/absolute/);
    expect(label.className).toMatch(/break-words/);
  });

  it("stacks vertically when orientation is vertical", () => {
    render(
      <WorkflowPipeline
        steps={[<WorkflowPipelineStep key="a" label="A" status="waiting" />]}
        orientation="vertical"
      />,
    );
    expect(screen.getByRole("list")).not.toHaveClass("sm:grid-cols-2");
    expect(screen.getByRole("list")).not.toHaveClass("md:flex-row");
  });

  it("shows the step's status badge with an accessible name", () => {
    render(
      <WorkflowPipeline
        steps={[<WorkflowPipelineStep key="a" label="Parser" status="degraded" />]}
      />,
    );
    expect(screen.getByLabelText("Degraded")).toBeInTheDocument();
  });

  it("shows a step's position and observed timestamp", () => {
    const { container } = render(
      <WorkflowPipeline
        steps={[
          <WorkflowPipelineStep
            key="a"
            position={1}
            label="Simulator"
            status="success"
            at="2026-09-20T10:00:00+00:00"
          />,
        ]}
      />,
    );
    expect(screen.getByText("1")).toBeInTheDocument();
    const time = container.querySelector("time");
    expect(time).not.toBeNull();
    expect(time).toHaveAttribute("datetime", "2026-09-20T10:00:00+00:00");
  });
});

describe("WorkflowConnectionIndicator", () => {
  it("renders a distinct label per connection state", () => {
    const states = ["connecting", "live", "reconnecting", "disconnected"] as const;
    const labels: Record<(typeof states)[number], string> = {
      connecting: "Connecting",
      live: "Live",
      reconnecting: "Reconnecting",
      disconnected: "Disconnected",
    };
    for (const state of states) {
      const { unmount } = render(<WorkflowConnectionIndicator status={state} />);
      expect(screen.getByText(labels[state])).toBeInTheDocument();
      unmount();
    }
  });
});

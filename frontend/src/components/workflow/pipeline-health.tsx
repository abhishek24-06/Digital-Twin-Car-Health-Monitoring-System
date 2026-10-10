"use client";

import type { WorkflowEventResponse, WorkflowStatusResponse } from "@/types/api";
import { WorkflowPipeline, WorkflowPipelineSteps } from "./pipeline";
import { PIPELINES, deriveStageStates } from "./pipelines";

interface PipelineHealthProps {
  events: WorkflowEventResponse[];
  workflowStatus?: WorkflowStatusResponse | null;
}

function PipelineHealthInner({ events, workflowStatus }: PipelineHealthProps) {
  const pipeline = PIPELINES.health;
  const states = deriveStageStates(events, pipeline.stages, {
    workflow: pipeline.id,
  });

  return (
    <WorkflowPipeline
      title={pipeline.title}
      orientation={pipeline.orientation}
      header={
        workflowStatus ? (
          <span className="text-xs text-ink-muted">
            {workflowStatus.subscriber_running
              ? "Subscriber running"
              : "Subscriber stopped"}
          </span>
        ) : undefined
      }
      steps={<WorkflowPipelineSteps stages={pipeline.stages} states={states} />}
    />
  );
}

export { PipelineHealthInner as PipelineHealth };

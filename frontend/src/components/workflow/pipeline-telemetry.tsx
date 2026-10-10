"use client";

import type { WorkflowEventResponse, WorkflowStatusResponse } from "@/types/api";
import { WorkflowPipeline, WorkflowPipelineSteps } from "./pipeline";
import { PIPELINES, deriveStageStates } from "./pipelines";

interface PipelineTelemetryProps {
  events: WorkflowEventResponse[];
  workflowStatus?: WorkflowStatusResponse | null;
}

function PipelineTelemetryInner({ events, workflowStatus }: PipelineTelemetryProps) {
  const pipeline = PIPELINES.telemetry;
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
            {workflowStatus.telemetry_pipeline_active
              ? "Pipeline active"
              : "Pipeline idle"}
          </span>
        ) : undefined
      }
      steps={<WorkflowPipelineSteps stages={pipeline.stages} states={states} />}
    />
  );
}

export { PipelineTelemetryInner as PipelineTelemetry };

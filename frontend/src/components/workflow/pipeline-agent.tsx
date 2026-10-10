"use client";

import type { WorkflowEventResponse } from "@/types/api";
import { WorkflowPipeline, WorkflowPipelineSteps } from "./pipeline";
import { PIPELINES, deriveStageStates } from "./pipelines";

interface PipelineAgentProps {
  events: WorkflowEventResponse[];
}

function PipelineAgentInner({ events }: PipelineAgentProps) {
  const pipeline = PIPELINES.agent;
  const states = deriveStageStates(events, pipeline.stages, {
    workflow: pipeline.id,
  });

  return (
    <WorkflowPipeline
      title={pipeline.title}
      orientation={pipeline.orientation}
      steps={<WorkflowPipelineSteps stages={pipeline.stages} states={states} />}
    />
  );
}

export { PipelineAgentInner as PipelineAgent };

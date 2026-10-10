"use client";

import type { WorkflowEventResponse } from "@/types/api";
import { WorkflowPipeline, WorkflowPipelineSteps } from "./pipeline";
import { PIPELINES, deriveStageStates } from "./pipelines";

interface PipelineRAGQueryProps {
  events: WorkflowEventResponse[];
}

function PipelineRAGQueryInner({ events }: PipelineRAGQueryProps) {
  const pipeline = PIPELINES.rag_query;
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

export { PipelineRAGQueryInner as PipelineRAGQuery };

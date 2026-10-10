"use client";

import type { WorkflowEventResponse } from "@/types/api";
import { WorkflowPipeline, WorkflowPipelineSteps } from "./pipeline";
import { PIPELINES, deriveStageStates } from "./pipelines";

interface PipelineRAGIngestionProps {
  events: WorkflowEventResponse[];
}

function PipelineRAGIngestionInner({ events }: PipelineRAGIngestionProps) {
  const pipeline = PIPELINES.rag_ingestion;
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

export { PipelineRAGIngestionInner as PipelineRAGIngestion };

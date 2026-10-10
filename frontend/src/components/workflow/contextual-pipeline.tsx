"use client";

import * as React from "react";
import type { VehicleTelemetryState } from "@/types/api";
import {
  WorkflowConnectionIndicator,
  WorkflowPipeline,
  WorkflowPipelineSteps,
} from "./pipeline";
import { PIPELINES, deriveStageStates, type PipelineId } from "./pipelines";
import { useWorkflowConnection, useWorkflowSlice } from "./workflow-stream-provider";

export interface ContextualPipelineProps {
  id: PipelineId;
  vehicleId?: string;
  documentId?: string;
  correlationId?: string;
  /**
   * Derived telemetry snapshot (from `GET /workflow/state`). Only meaningful
   * for the `telemetry` pipeline; overlays real process/DB state on top of the
   * bridged lifecycle events.
   */
  derivedState?: VehicleTelemetryState | null;
  /**
   * When true (default) the pipeline renders nothing until at least one stage
   * has a real signal, so a page never shows a fabricated "in progress" flow.
   */
  hideWhenEmpty?: boolean;
}

/**
 * Renders one live workflow pipeline, scoped to a page entity and wired to the
 * single shared stream. Real events and derived state only — no fake progress.
 */
export function ContextualPipeline({
  id,
  vehicleId,
  documentId,
  correlationId,
  derivedState,
  hideWhenEmpty = true,
}: ContextualPipelineProps) {
  const pipeline = PIPELINES[id];
  const connection = useWorkflowConnection();
  const { events } = useWorkflowSlice({ workflow: id, vehicleId, documentId, correlationId });

  const stageStates = React.useMemo(
    () => deriveStageStates(events, pipeline.stages, { workflow: id, derivedState }),
    [events, pipeline.stages, id, derivedState],
  );

  const hasSignal = stageStates.some((state) => state.status !== "waiting");
  if (hideWhenEmpty && !hasSignal) {
    return null;
  }

  return (
    <WorkflowPipeline
      title={pipeline.title}
      orientation={pipeline.orientation}
      header={<WorkflowConnectionIndicator status={connection} />}
      steps={<WorkflowPipelineSteps stages={pipeline.stages} states={stageStates} />}
    />
  );
}
